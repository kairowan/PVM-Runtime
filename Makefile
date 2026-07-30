PYTHON ?= python3
BUILD_DIR ?= build/client
PYTHONPATH_VALUE := $(CURDIR)/server/src
ANDROID_SDK_PATH ?= $(firstword $(wildcard $(ANDROID_SDK_ROOT) $(ANDROID_HOME) $(HOME)/Library/Android/sdk $(HOME)/Desktop/android/sdk))
HARMONY_DEVICE_TARGET ?=
HARMONY_SIGNED_HAP ?=
PVM_KMP_GRADLE_HOME ?= $(CURDIR)/build/gradle-kmp-home
FUZZ_CXX := $(firstword $(wildcard /opt/homebrew/opt/llvm/bin/clang++ /usr/local/opt/llvm/bin/clang++))
ifeq ($(FUZZ_CXX),)
FUZZ_CXX := clang++
endif

.PHONY: android-demo-apk android-demo-check android-packages android-production-packages bootstrap build compatibility delivery-matrix docs-check fuzz-check generate-host-idl harmony-demo-run harmony-demo-screenshot harmony-device-run harmony-device-screenshot harmony-packages harmony-production-check harmony-sdk-check host-manifest ios-demo-app ios-demo-check ios-demo-run ios-demo-screenshot ios-device-archive ios-packages ios-sdk-check kmp-check kmp-packages publish release-check sanitizer-check serve demo platform-check test verify-contracts

bootstrap:
	PYTHONPATH="$(PYTHONPATH_VALUE)" $(PYTHON) -m pvm_server.keys --directory server/var/keys

build:
	cmake -S client -B "$(BUILD_DIR)" -DCMAKE_BUILD_TYPE=Release
	cmake --build "$(BUILD_DIR)" -j

android-packages:
	@test -n "$(ANDROID_SDK_PATH)" || (echo "Android SDK not found; set ANDROID_SDK_PATH" && exit 1)
	ANDROID_HOME="$(ANDROID_SDK_PATH)" client/platform/android/gradlew \
		-p client/platform/android --no-daemon \
		:runtime:lintDebug :demo:lintDebug \
		:runtime:publishReleasePublicationToBundleRepository \
		:demo:assembleDebug :demo:assembleMinified :demo:bundleDebug
	mkdir -p dist/android/maven
	cp client/platform/android/demo/build/outputs/apk/debug/demo-debug.apk \
		dist/android/PVMRuntime-demo-debug.apk
	cp client/platform/android/demo/build/outputs/bundle/debug/demo-debug.aab \
		dist/android/PVMRuntime-demo-debug.aab
	cp client/platform/android/demo/build/outputs/apk/minified/demo-minified.apk \
		dist/android/PVMRuntime-demo-minified-smoke.apk
	cp client/platform/android/runtime/build/outputs/aar/runtime-release.aar \
		dist/android/pvm-runtime-0.5.0.aar
	cp -R client/platform/android/runtime/build/repository/. dist/android/maven/
	@echo "APK: $(CURDIR)/dist/android/PVMRuntime-demo-debug.apk"
	@echo "AAB: $(CURDIR)/dist/android/PVMRuntime-demo-debug.aab"
	@echo "R8 smoke: $(CURDIR)/dist/android/PVMRuntime-demo-minified-smoke.apk"
	@echo "AAR: $(CURDIR)/dist/android/pvm-runtime-0.5.0.aar"
	@echo "Maven: $(CURDIR)/dist/android/maven"

android-demo-apk: android-packages

android-demo-check: build android-packages
	ANDROID_HOME="$(ANDROID_SDK_PATH)" $(PYTHON) scripts/check_android_artifacts.py

android-production-packages:
	@test -n "$(ANDROID_SDK_PATH)" || (echo "Android SDK not found; set ANDROID_SDK_PATH" && exit 1)
	ANDROID_HOME="$(ANDROID_SDK_PATH)" client/platform/android/gradlew \
		-p client/platform/android --no-daemon \
		:demo:verifyProductionSigning :demo:assembleRelease :demo:bundleRelease
	mkdir -p dist/android
	cp client/platform/android/demo/build/outputs/apk/release/demo-release.apk \
		dist/android/PVMRuntime-demo-release.apk
	cp client/platform/android/demo/build/outputs/bundle/release/demo-release.aab \
		dist/android/PVMRuntime-demo-release.aab

ios-packages:
	$(PYTHON) scripts/build_ios_artifacts.py

ios-sdk-check: ios-packages
	$(PYTHON) scripts/check_ios_artifacts.py

ios-demo-app:
	xcodebuild -quiet \
		-project client/platform/ios/demo/PVMRuntimeDemo.xcodeproj \
		-scheme PVMRuntimeDemo \
		-configuration Debug \
		-sdk iphonesimulator \
		-destination 'generic/platform=iOS Simulator' \
		-derivedDataPath build/ios-demo/DerivedData \
		SWIFT_VERSION=6 SWIFT_STRICT_CONCURRENCY=complete \
		build

ios-demo-check: build ios-demo-app
	$(PYTHON) scripts/check_ios_demo.py

ios-demo-run: ios-demo-check
	$(PYTHON) scripts/run_ios_demo.py

ios-demo-screenshot: ios-demo-check
	$(PYTHON) scripts/run_ios_demo.py \
		--reset --seed-screenshot --screenshot docs/assets/ios-demo.png

ios-device-archive:
	$(PYTHON) scripts/build_ios_device_archive.py

harmony-packages: delivery-matrix
	$(PYTHON) scripts/build_harmony_artifacts.py

harmony-sdk-check: build harmony-packages
	$(PYTHON) scripts/check_harmony_artifacts.py

harmony-demo-run: harmony-sdk-check
	$(PYTHON) scripts/run_harmony_demo.py

harmony-demo-screenshot: harmony-sdk-check
	$(PYTHON) scripts/run_harmony_demo.py \
		--reset --seed-screenshot --screenshot docs/assets/harmony-demo.png

harmony-device-run:
	@test -n "$(HARMONY_DEVICE_TARGET)" || (echo "Set HARMONY_DEVICE_TARGET to the USB target ID" && exit 1)
	@test -f "$(HARMONY_SIGNED_HAP)" || (echo "Set HARMONY_SIGNED_HAP to a Huawei-signed HAP" && exit 1)
	HARMONY_HAP="$(HARMONY_SIGNED_HAP)" $(PYTHON) scripts/run_harmony_demo.py \
		--physical --target "$(HARMONY_DEVICE_TARGET)"

harmony-device-screenshot:
	@test -n "$(HARMONY_DEVICE_TARGET)" || (echo "Set HARMONY_DEVICE_TARGET to the USB target ID" && exit 1)
	@test -f "$(HARMONY_SIGNED_HAP)" || (echo "Set HARMONY_SIGNED_HAP to a Huawei-signed HAP" && exit 1)
	HARMONY_HAP="$(HARMONY_SIGNED_HAP)" $(PYTHON) scripts/run_harmony_demo.py \
		--physical --target "$(HARMONY_DEVICE_TARGET)" \
		--reset --seed-screenshot --screenshot docs/assets/harmony-demo.png

harmony-production-check:
	@test -f "$(HARMONY_SIGNED_HAP)" || (echo "Set HARMONY_SIGNED_HAP to a Huawei-signed HAP" && exit 1)
	HARMONY_HAP="$(HARMONY_SIGNED_HAP)" $(PYTHON) scripts/check_harmony_release.py

kmp-check:
	GRADLE_USER_HOME="$(PVM_KMP_GRADLE_HOME)" \
		client/platform/android/gradlew -p client/platform/kmp --no-daemon \
		compileKotlinMetadata jvmTest compileKotlinIosSimulatorArm64

kmp-packages: kmp-check
	GRADLE_USER_HOME="$(PVM_KMP_GRADLE_HOME)" \
		client/platform/android/gradlew -p client/platform/kmp --no-daemon \
		publishAllPublicationsToBundleRepository
	mkdir -p dist/kmp/maven
	cp -R client/platform/kmp/build/repository/. dist/kmp/maven/

host-manifest:
	PYTHONPATH="$(PYTHONPATH_VALUE)" $(PYTHON) -m pvm_server.host_manifest \
		server/sample/counter.pvm.json --output build/host-capabilities.json

generate-host-idl:
	PYTHONPATH="$(PYTHONPATH_VALUE)" $(PYTHON) -m pvm_server.host_idl \
		--idl spec/host_idl.json --output generated/host

delivery-matrix: bootstrap generate-host-idl
	PYTHONPATH="$(PYTHONPATH_VALUE)" $(PYTHON) -m pvm_server.delivery_build \
		server/sample/counter.pvm.json \
		--private-key server/var/keys/dev-private.pem \
		--public-key server/var/keys/dev-public.pem \
		--output build/delivery --all

compatibility: bootstrap build
	PYTHONPATH="$(PYTHONPATH_VALUE)" $(PYTHON) -m pvm_server.compatibility \
		--private-key server/var/keys/dev-private.pem \
		--public-key server/var/keys/dev-public.pem \
		--runtime "$(CURDIR)/$(BUILD_DIR)/pvm_cli" \
		--output build/compatibility

verify-contracts:
	PYTHONPATH="$(PYTHONPATH_VALUE)" $(PYTHON) -m pvm_server.host_idl --check
	PYTHONPATH="$(PYTHONPATH_VALUE)" $(PYTHON) -m pvm_server.conformance
	PYTHONPATH="$(PYTHONPATH_VALUE)" $(PYTHON) -m pvm_server.tooling lint \
		server/sample/counter.pvm.json

docs-check:
	$(PYTHON) scripts/check_docs.py

release-check: test platform-check kmp-check verify-contracts docs-check delivery-matrix compatibility sanitizer-check fuzz-check

publish: bootstrap
	PYTHONPATH="$(PYTHONPATH_VALUE)" $(PYTHON) -m pvm_server.publish \
		server/sample/counter.pvm.json \
		--private-key server/var/keys/dev-private.pem \
		--repository server/var/repository

serve:
	PYTHONPATH="$(PYTHONPATH_VALUE)" $(PYTHON) -m pvm_server.serve \
		--repository server/var/repository

demo: bootstrap build
	PYTHONPATH="$(PYTHONPATH_VALUE)" $(PYTHON) scripts/demo.py

platform-check: build
	$(PYTHON) scripts/check_platform_hosts.py

test: build
	PYTHONPATH="$(PYTHONPATH_VALUE)" PVM_RUNTIME="$(CURDIR)/$(BUILD_DIR)/pvm_cli" \
		$(PYTHON) tests/test_e2e.py

sanitizer-check:
	cmake -S client -B build/sanitized -DCMAKE_BUILD_TYPE=RelWithDebInfo \
		-DPVM_ENABLE_SANITIZERS=ON
	cmake --build build/sanitized -j
	PYTHONPATH="$(PYTHONPATH_VALUE)" PVM_RUNTIME="$(CURDIR)/build/sanitized/pvm_cli" \
		ASAN_OPTIONS=detect_leaks=0 $(PYTHON) tests/test_e2e.py

fuzz-check: bootstrap
	cmake -S client -B build/fuzz-libfuzzer -DCMAKE_BUILD_TYPE=RelWithDebInfo \
		-DCMAKE_CXX_COMPILER="$(FUZZ_CXX)" -DPVM_BUILD_TOOLS=OFF -DPVM_BUILD_FUZZER=ON
	cmake --build build/fuzz-libfuzzer -j
	mkdir -p build/fuzz-corpus
	PYTHONPATH="$(PYTHONPATH_VALUE)" $(PYTHON) -m pvm_server.compiler \
		server/sample/counter.pvm.json --private-key server/var/keys/dev-private.pem \
		--output build/fuzz-corpus/counter.pvm
	build/fuzz-libfuzzer/pvm_package_fuzz -runs=1000 build/fuzz-corpus
