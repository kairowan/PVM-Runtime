#include "main_window.h"

#include <QApplication>
#include <QCoreApplication>

#include <cstring>
#include <iostream>

int main(int argc, char *argv[]) {
  if (argc == 2 && std::strcmp(argv[1], "--self-test") == 0) {
    QCoreApplication application(argc, argv);
    if (!studio::selfTest()) {
      std::cerr << "migration studio self-test failed\n";
      return 1;
    }
    std::cout << "migration studio self-test passed\n";
    return 0;
  }

  QApplication application(argc, argv);
  QCoreApplication::setApplicationName("PVM Migration Studio");
  QCoreApplication::setApplicationVersion(PVM_STUDIO_VERSION);
  QCoreApplication::setOrganizationName("PVM Runtime");

  MigrationStudioWindow window;
  window.show();
  return application.exec();
}
