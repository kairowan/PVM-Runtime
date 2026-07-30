#include "pvm/runtime.hpp"

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace {

class FuzzHost final : public pvm::UiHost, public pvm::CapabilityHost {
 public:
  void replace_tree(const pvm::UiNodeSnapshot&) override {}

  pvm::Value invoke(const std::string&, const std::string&,
                    const std::vector<pvm::Value>&) override {
    return std::string{};
  }

  void begin_async(std::uint64_t, const std::string&, const std::string&,
                   const std::vector<pvm::Value>&) override {}
};

}  // namespace

extern "C" int LLVMFuzzerTestOneInput(const std::uint8_t* data, std::size_t size) {
  if (size > 16U * 1024U * 1024U) {
    return 0;
  }
  static FuzzHost host;
  try {
    const std::vector<std::uint8_t> package(data, data + size);
    auto runtime = pvm::Runtime::load_package_bound(
        package, "", "com.example.protected", "enterprise", "desktop",
        "online_provisioned", 0, host, host,
        [](const std::uint8_t*, std::size_t, const std::uint8_t*, std::size_t,
           const std::string&) { return true; });
    static_cast<void>(runtime);
  } catch (const std::exception&) {
  }
  return 0;
}
