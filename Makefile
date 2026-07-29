PYTHON ?= python3
BUILD_DIR ?= build/client
PYTHONPATH_VALUE := $(CURDIR)/server/src
FUZZ_CXX := $(firstword $(wildcard /opt/homebrew/opt/llvm/bin/clang++ /usr/local/opt/llvm/bin/clang++))
ifeq ($(FUZZ_CXX),)
FUZZ_CXX := clang++
endif

.PHONY: bootstrap build compatibility delivery-matrix docs-check fuzz-check generate-host-idl host-manifest publish release-check sanitizer-check serve demo platform-check test verify-contracts

bootstrap:
	PYTHONPATH="$(PYTHONPATH_VALUE)" $(PYTHON) -m pvm_server.keys --directory server/var/keys

build:
	cmake -S client -B "$(BUILD_DIR)" -DCMAKE_BUILD_TYPE=Release
	cmake --build "$(BUILD_DIR)" -j

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

release-check: test platform-check verify-contracts docs-check delivery-matrix compatibility sanitizer-check fuzz-check

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
