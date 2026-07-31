import XCTest
import UIKit
@testable import PVMRuntime

@MainActor
final class PVMRendererPerformanceTests: XCTestCase {
    func testUIKitIncrementalCommitBeatsFullNativeRebind() throws {
        let root = UIView()
        let renderer = PVMUIKitRenderer(root: root)
        let batches = try makeBatches()
        XCTAssertNil(batches[1].root)
        let events: PVMUIKitRenderer.EventSink = { _, _, _ in }
        try renderer.apply(batches[0], events: events)

        let labels =
            (0..<Self.nodeCount).map { index in
                UILabel().withText("Stable node \(index)")
            }
        let optimized = UILabel().withText("Dynamic 0")
        for update in 0..<Self.warmupCount {
            try! renderer.apply(batches[update + 1], events: events)
            rebind(labels, update: update)
            bind(optimized, text: "Dynamic \(update)")
        }

        var pvm = [UInt64]()
        var fullNative = [UInt64]()
        var optimizedNative = [UInt64]()
        pvm.reserveCapacity(Self.sampleCount)
        fullNative.reserveCapacity(Self.sampleCount)
        optimizedNative.reserveCapacity(Self.sampleCount)
        for sample in 0..<Self.sampleCount {
            let update = Self.warmupCount + sample + 1
            let operations: [() -> Void] = [
                { pvm.append(self.timed { try! renderer.apply(batches[update], events: events) }) },
                { fullNative.append(self.timed { self.rebind(labels, update: update) }) },
                {
                    optimizedNative.append(
                        self.timed { self.bind(optimized, text: "Dynamic \(update)") }
                    )
                },
            ]
            let offset = sample % operations.count
            for index in 0..<operations.count {
                operations[(index + offset) % operations.count]()
            }
        }

        let pvmStats = stats(pvm)
        let fullStats = stats(fullNative)
        let optimizedStats = stats(optimizedNative)
        print(
            "PvmIOSRenderBenchmark " +
                [
                    "nodes": Self.nodeCount,
                    "samples": Self.sampleCount,
                    "unit": "microseconds",
                    "pvmIncremental": pvmStats.dictionary,
                    "nativeFullRebind": fullStats.dictionary,
                    "nativeOptimizedLeafUpdate": optimizedStats.dictionary,
                ].json
        )
        XCTAssertLessThan(pvmStats.p95, fullStats.p95)
        XCTAssertLessThan(pvmStats.p95, 16_667)
    }

    func testSwiftUIStateCommitSkipsWholeTreeBookkeeping() throws {
        let exactTree = PVMSwiftUITree()
        let fullTree = PVMSwiftUITree()
        let exact = try makeBatches()
        let full = try makeBatches(structureChanged: true)
        let events: (UInt32, String, String?) -> Void = { _, _, _ in }
        try exactTree.apply(exact[0], events: events)
        try fullTree.apply(full[0], events: events)
        for update in 0..<Self.warmupCount {
            try! exactTree.apply(exact[update + 1], events: events)
            try! fullTree.apply(full[update + 1], events: events)
        }
        var exactSamples = [UInt64]()
        var fullSamples = [UInt64]()
        for sample in 0..<Self.sampleCount {
            let update = Self.warmupCount + sample + 1
            exactSamples.append(timed { try! exactTree.apply(exact[update], events: events) })
            fullSamples.append(timed { try! fullTree.apply(full[update], events: events) })
        }
        let exactStats = stats(exactSamples)
        let fullStats = stats(fullSamples)
        print(
            "PvmSwiftUIStateBenchmark " +
                [
                    "nodes": Self.nodeCount,
                    "samples": Self.sampleCount,
                    "unit": "microseconds",
                    "exactChanged": exactStats.dictionary,
                    "fullBookkeeping": fullStats.dictionary,
                ].json
        )
        XCTAssertLessThan(exactStats.p95, fullStats.p95)
    }

    private func makeBatches(structureChanged: Bool = false) throws -> [PVMUIBatch] {
        try (0...(Self.warmupCount + Self.sampleCount)).map { update in
            let children: [[String: Any]] =
                (0..<Self.nodeCount).map { index in
                    [
                        "type": "Text",
                        "id": index + 2,
                        "revision": index == Self.changedIndex ? update + 1 : 1,
                        "props": [
                            "text":
                                index == Self.changedIndex
                                ? "Dynamic \(update)"
                                : "Stable node \(index)",
                        ],
                        "events": [],
                        "children": [],
                    ]
                }
            let payload: [String: Any]
            if update == 0 || structureChanged {
                payload = [
                    "wireVersion": 2,
                    "operation": "replace",
                    "structureChanged": true,
                    "changed": update == 0 ? [] : [Self.changedIndex + 2],
                    "root": [
                        "type": "Column",
                        "id": 1,
                        "revision": update + 1,
                        "props": [:],
                        "events": [],
                        "children": children,
                    ],
                ]
            } else {
                payload = [
                    "wireVersion": 2,
                    "operation": "patch",
                    "structureChanged": false,
                    "rootId": 1,
                    "rootType": "Column",
                    "rootRevision": update + 1,
                    "changed": [Self.changedIndex + 2],
                    "nodes": [children[Self.changedIndex]],
                    "revisions": [
                        ["id": 1, "revision": update + 1],
                        ["id": Self.changedIndex + 2, "revision": update + 1],
                    ],
                ]
            }
            return try JSONDecoder().decode(
                PVMUIBatch.self,
                from: JSONSerialization.data(withJSONObject: payload)
            )
        }
    }

    private func rebind(_ labels: [UILabel], update: Int) {
        for (index, label) in labels.enumerated() {
            bind(
                label,
                text: index == Self.changedIndex ? "Dynamic \(update)" : "Stable node \(index)"
            )
        }
    }

    private func bind(_ label: UILabel, text: String) {
        label.accessibilityLabel = nil
        label.isUserInteractionEnabled = true
        label.text = text
    }

    private func timed(_ operation: () -> Void) -> UInt64 {
        let started = DispatchTime.now().uptimeNanoseconds
        operation()
        return DispatchTime.now().uptimeNanoseconds - started
    }

    private func stats(_ samples: [UInt64]) -> Stats {
        let sorted = samples.sorted()
        return Stats(
            median: sorted[sorted.count / 2] / 1_000,
            p95: sorted[min(sorted.count * 95 / 100, sorted.count - 1)] / 1_000
        )
    }

    private struct Stats {
        let median: UInt64
        let p95: UInt64

        var dictionary: [String: UInt64] {
            ["median": median, "p95": p95]
        }
    }

    private static let nodeCount = 240
    private static let changedIndex = nodeCount / 2
    private static let warmupCount = 20
    private static let sampleCount = 180
}

private extension UILabel {
    func withText(_ text: String) -> UILabel {
        self.text = text
        return self
    }
}

private extension Dictionary where Key == String, Value == Any {
    var json: String {
        let data = try! JSONSerialization.data(withJSONObject: self, options: [.sortedKeys])
        return String(decoding: data, as: UTF8.self)
    }
}
