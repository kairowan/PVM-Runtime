#pragma once

#include <QByteArray>
#include <QMainWindow>
#include <QProcess>
#include <QStringList>

#include <functional>

class QCheckBox;
class QComboBox;
class QLabel;
class QLineEdit;
class QPlainTextEdit;
class QProgressBar;
class QPushButton;
class QSpinBox;
class QTabWidget;

namespace studio {

QStringList splitSelectors(const QString &value);
QString stageLabel(const QString &stage);
bool isEditableReviewFile(const QString &name);
bool selfTest();
bool processSelfTest();

}  // namespace studio

class MigrationStudioWindow final : public QMainWindow {
 public:
  enum class Operation {
    None,
    Scan,
    Convert,
    StructuralVerify,
    StrictVerify,
  };

  explicit MigrationStudioWindow(QWidget *parent = nullptr);
  ~MigrationStudioWindow() override;

 private:
  void buildUi();
  QWidget *buildMigrationTab();
  QWidget *buildReviewTab();
  QWidget *buildLogTab();
  QWidget *pathField(QLineEdit *edit, const QString &buttonText,
                     const std::function<void()> &browse);

  void chooseSource();
  void chooseOutput();
  void chooseFile(QLineEdit *target, const QString &caption);
  void start(Operation operation);
  void cancel();
  void setRunning(bool running);
  bool validate(Operation operation, QString *error) const;
  QStringList commandArguments(Operation operation) const;
  QStringList selectorArguments() const;
  QProcessEnvironment processEnvironment() const;
  QString hostIdlPath() const;

  void readStdout();
  void readStderr();
  void consumeLines(QByteArray *buffer, const QByteArray &incoming, bool events);
  void handleEventLine(const QByteArray &line);
  void processFinished(int exitCode, QProcess::ExitStatus exitStatus);
  void appendLog(const QString &level, const QString &message);
  QString safeForLog(QString message) const;

  QString selectedReviewPath() const;
  void reloadReview();
  void saveReview();
  void openOutput();
  void exportLog();

  const QString repoRoot_;
  Operation operation_{Operation::None};
  QProcess *process_{nullptr};
  QByteArray stdoutBuffer_;
  QByteArray stderrBuffer_;

  QTabWidget *tabs_{nullptr};
  QLineEdit *sourceEdit_{nullptr};
  QLineEdit *outputEdit_{nullptr};
  QLineEdit *pythonEdit_{nullptr};
  QPlainTextEdit *classesEdit_{nullptr};
  QPlainTextEdit *modulesEdit_{nullptr};
  QCheckBox *dependenciesCheck_{nullptr};
  QCheckBox *forceCheck_{nullptr};
  QLineEdit *applicationIdEdit_{nullptr};
  QLineEdit *moduleIdEdit_{nullptr};
  QLineEdit *channelEdit_{nullptr};
  QComboBox *platformCombo_{nullptr};
  QComboBox *profileCombo_{nullptr};
  QSpinBox *releaseSpin_{nullptr};
  QLineEdit *runtimeEdit_{nullptr};
  QLineEdit *privateKeyEdit_{nullptr};
  QLineEdit *publicKeyEdit_{nullptr};
  QPushButton *scanButton_{nullptr};
  QPushButton *convertButton_{nullptr};
  QPushButton *structuralButton_{nullptr};
  QPushButton *strictButton_{nullptr};
  QPushButton *cancelButton_{nullptr};
  QProgressBar *progress_{nullptr};
  QLabel *statusLabel_{nullptr};

  QComboBox *reviewFileCombo_{nullptr};
  QPlainTextEdit *reviewEditor_{nullptr};
  QLabel *reviewStatus_{nullptr};
  QPushButton *reviewSaveButton_{nullptr};
  QPlainTextEdit *logEdit_{nullptr};
};
