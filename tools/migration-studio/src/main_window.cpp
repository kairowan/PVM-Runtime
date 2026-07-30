#include "main_window.h"

#include <QCheckBox>
#include <QColor>
#include <QComboBox>
#include <QCoreApplication>
#include <QDateTime>
#include <QDesktopServices>
#include <QDir>
#include <QFile>
#include <QFileDialog>
#include <QFileInfo>
#include <QFontDatabase>
#include <QFormLayout>
#include <QGroupBox>
#include <QHash>
#include <QHBoxLayout>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonParseError>
#include <QLabel>
#include <QLineEdit>
#include <QMessageBox>
#include <QPlainTextEdit>
#include <QPointer>
#include <QProcessEnvironment>
#include <QProgressBar>
#include <QPushButton>
#include <QSaveFile>
#include <QScrollArea>
#include <QSpinBox>
#include <QStandardPaths>
#include <QTabWidget>
#include <QTextBlock>
#include <QTextCharFormat>
#include <QTextCursor>
#include <QTemporaryFile>
#include <QTimer>
#include <QUrl>
#include <QVBoxLayout>

#include <algorithm>
#include <functional>

namespace {

QString cleanAbsolutePath(const QString &value) {
  return QFileInfo(QDir::cleanPath(value.trimmed())).absoluteFilePath();
}

QString discoverRepoRoot() {
  for (const QString &start :
       {QCoreApplication::applicationDirPath(), QDir::currentPath()}) {
    QDir directory(start);
    do {
      if (QFileInfo(directory.filePath(
                        QStringLiteral("server/src/pvm_server/migrate.py")))
              .isFile() &&
          QFileInfo(directory.filePath(QStringLiteral("spec/host_idl.json")))
              .isFile()) {
        return directory.absolutePath();
      }
    } while (directory.cdUp());
  }
  return QDir::currentPath();
}

QString operationName(MigrationStudioWindow::Operation operation) {
  switch (operation) {
    case MigrationStudioWindow::Operation::Scan:
      return QStringLiteral("扫描 / Scan");
    case MigrationStudioWindow::Operation::Convert:
      return QStringLiteral("生成 / Convert");
    case MigrationStudioWindow::Operation::StructuralVerify:
      return QStringLiteral("结构验证 / Structural verify");
    case MigrationStudioWindow::Operation::StrictVerify:
      return QStringLiteral("严格验证 / Strict verify");
    case MigrationStudioWindow::Operation::None:
      return QStringLiteral("空闲 / Idle");
  }
  return QStringLiteral("未知 / Unknown");
}

QString compactCommand(const QString &program, const QStringList &arguments) {
  QStringList values{program};
  for (const QString &argument : arguments) {
    QString value = argument;
    if (value.contains(QLatin1Char(' ')) || value.contains(QLatin1Char('"'))) {
      value.replace(QLatin1Char('"'), QStringLiteral("\\\""));
      value = QLatin1Char('"') + value + QLatin1Char('"');
    }
    values.append(value);
  }
  return values.join(QLatin1Char(' '));
}

}  // namespace

namespace studio {

QStringList splitSelectors(const QString &value) {
  QStringList result;
  for (const QString &line : value.split(QLatin1Char('\n'))) {
    const QString item = line.trimmed();
    if (!item.isEmpty() && !result.contains(item)) {
      result.append(item);
    }
  }
  return result;
}

QString stageLabel(const QString &stage) {
  static const QHash<QString, QString> labels{
      {QStringLiteral("prepare"), QStringLiteral("准备 / Prepare")},
      {QStringLiteral("scan"), QStringLiteral("扫描 / Scan")},
      {QStringLiteral("generate"), QStringLiteral("生成 / Generate")},
      {QStringLiteral("source"), QStringLiteral("源码指纹 / Source")},
      {QStringLiteral("dsl"), QStringLiteral("DSL 编译 / DSL")},
      {QStringLiteral("reviews"), QStringLiteral("人工复核 / Reviews")},
      {QStringLiteral("capabilities"), QStringLiteral("能力审批 / Capabilities")},
      {QStringLiteral("behavior"), QStringLiteral("VM 行为 / Behavior")},
      {QStringLiteral("complete"), QStringLiteral("完成 / Complete")},
      {QStringLiteral("failed"), QStringLiteral("失败 / Failed")},
  };
  return labels.value(stage, stage);
}

bool isEditableReviewFile(const QString &name) {
  return name == QStringLiteral("migration-approvals.json") ||
         name == QStringLiteral("capabilities.json") ||
         name == QStringLiteral("migration-cases.json") ||
         name == QStringLiteral("module.pvm.json");
}

bool selfTest() {
  return splitSelectors(QStringLiteral(" A\n\nB\nA \n")).join(QLatin1Char(',')) ==
             QStringLiteral("A,B") &&
         stageLabel(QStringLiteral("behavior")).contains(QStringLiteral("VM")) &&
         stageLabel(QStringLiteral("custom")) == QStringLiteral("custom") &&
         isEditableReviewFile(QStringLiteral("module.pvm.json")) &&
         !isEditableReviewFile(QStringLiteral("verification.json"));
}

bool processSelfTest() {
  QProcess process;
  const QString python =
      QStandardPaths::findExecutable(QStringLiteral("python3"));
  if (python.isEmpty()) {
    return false;
  }
  process.start(python,
                {QStringLiteral("-c"),
                 QStringLiteral("print('pvm-migration-studio-process')")});
  return process.waitForStarted(5000) && process.waitForFinished(5000) &&
         process.exitStatus() == QProcess::NormalExit &&
         process.exitCode() == 0 &&
         process.readAllStandardOutput().trimmed() ==
             QByteArray("pvm-migration-studio-process");
}

}  // namespace studio

MigrationStudioWindow::MigrationStudioWindow(QWidget *parent)
    : QMainWindow(parent), repoRoot_(discoverRepoRoot()) {
  buildUi();
  setWindowTitle(QStringLiteral("PVM Migration Studio"));
  resize(1180, 820);
  setMinimumSize(900, 680);
}

MigrationStudioWindow::~MigrationStudioWindow() {
  if (process_ != nullptr && process_->state() != QProcess::NotRunning) {
    process_->kill();
    process_->waitForFinished(1000);
  }
}

void MigrationStudioWindow::buildUi() {
  auto *central = new QWidget(this);
  auto *layout = new QVBoxLayout(central);
  layout->setContentsMargins(20, 18, 20, 18);
  layout->setSpacing(14);

  auto *title = new QLabel(QStringLiteral("PVM Migration Studio"), central);
  title->setObjectName(QStringLiteral("title"));
  auto *subtitle = new QLabel(
      QStringLiteral("选择性迁移、审批与 C++17 VM 严格验证 / Selective migration, "
                     "review and strict verification"),
      central);
  subtitle->setObjectName(QStringLiteral("subtitle"));
  layout->addWidget(title);
  layout->addWidget(subtitle);

  tabs_ = new QTabWidget(central);
  tabs_->addTab(buildMigrationTab(), QStringLiteral("迁移 / Migrate"));
  tabs_->addTab(buildReviewTab(), QStringLiteral("复核 / Review"));
  tabs_->addTab(buildLogTab(), QStringLiteral("日志 / Logs"));
  layout->addWidget(tabs_, 1);
  setCentralWidget(central);

  setStyleSheet(QStringLiteral(R"(
    QMainWindow, QWidget { background: #0b1220; color: #dbe7f5; }
    QLabel#title { font-size: 26px; font-weight: 700; color: #f8fbff; }
    QLabel#subtitle { color: #8fa8c4; margin-bottom: 4px; }
    QTabWidget::pane { border: 1px solid #23344c; border-radius: 10px; background: #101a2b; }
    QTabBar::tab { background: #101a2b; color: #8fa8c4; padding: 10px 18px; }
    QTabBar::tab:selected { color: #75e3ec; border-bottom: 2px solid #33c5d3; }
    QGroupBox { border: 1px solid #23344c; border-radius: 8px; margin-top: 12px;
                padding-top: 12px; font-weight: 600; }
    QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #9db4cf; }
    QLineEdit, QPlainTextEdit, QComboBox, QSpinBox {
      background: #08101d; border: 1px solid #2b405b; border-radius: 6px;
      padding: 7px; selection-background-color: #147a88;
    }
    QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus {
      border-color: #33c5d3;
    }
    QPushButton { background: #1c334d; border: 1px solid #31516f; border-radius: 6px;
                  padding: 8px 13px; }
    QPushButton:hover { background: #244461; }
    QPushButton:disabled { color: #62758a; background: #162234; }
    QPushButton#primary { background: #147a88; border-color: #33c5d3; font-weight: 700; }
    QPushButton#danger { background: #642f3a; border-color: #a54a5d; }
    QProgressBar { background: #08101d; border: 1px solid #2b405b; border-radius: 6px;
                   text-align: center; min-height: 20px; }
    QProgressBar::chunk { background: #25b8c5; border-radius: 5px; }
    QScrollArea { border: 0; }
  )"));
}

QWidget *MigrationStudioWindow::pathField(
    QLineEdit *edit, const QString &buttonText,
    const std::function<void()> &browse) {
  auto *container = new QWidget;
  auto *layout = new QHBoxLayout(container);
  layout->setContentsMargins(0, 0, 0, 0);
  layout->setSpacing(8);
  layout->addWidget(edit, 1);
  auto *button = new QPushButton(buttonText, container);
  connect(button, &QPushButton::clicked, this, browse);
  layout->addWidget(button);
  return container;
}

QWidget *MigrationStudioWindow::buildMigrationTab() {
  auto *page = new QWidget;
  auto *pageLayout = new QVBoxLayout(page);
  pageLayout->setContentsMargins(0, 0, 0, 0);

  auto *scroll = new QScrollArea(page);
  scroll->setWidgetResizable(true);
  auto *content = new QWidget(scroll);
  auto *layout = new QVBoxLayout(content);
  layout->setContentsMargins(18, 16, 18, 16);
  layout->setSpacing(14);

  auto *paths = new QGroupBox(QStringLiteral("项目路径 / Project paths"), content);
  auto *pathsForm = new QFormLayout(paths);
  sourceEdit_ = new QLineEdit(paths);
  sourceEdit_->setPlaceholderText(QStringLiteral("/path/to/legacy-project"));
  outputEdit_ = new QLineEdit(
      QDir(repoRoot_).filePath(QStringLiteral("build/migration-studio-output")),
      paths);
  pythonEdit_ = new QLineEdit(
      QStandardPaths::findExecutable(QStringLiteral("python3")), paths);
  pathsForm->addRow(
      QStringLiteral("老项目 / Source"),
      pathField(sourceEdit_, QStringLiteral("选择… / Browse"), [this] {
        chooseSource();
      }));
  pathsForm->addRow(
      QStringLiteral("输出目录 / Output"),
      pathField(outputEdit_, QStringLiteral("选择… / Browse"), [this] {
        chooseOutput();
      }));
  pathsForm->addRow(
      QStringLiteral("Python"),
      pathField(pythonEdit_, QStringLiteral("选择… / Browse"), [this] {
        chooseFile(pythonEdit_, QStringLiteral("选择 Python / Select Python"));
      }));
  layout->addWidget(paths);

  auto *selection =
      new QGroupBox(QStringLiteral("选择范围 / Selection"), content);
  auto *selectionLayout = new QHBoxLayout(selection);
  classesEdit_ = new QPlainTextEdit(selection);
  classesEdit_->setPlaceholderText(
      QStringLiteral("每行一个类 / One class per line\nCheckoutViewModel"));
  classesEdit_->setMaximumHeight(115);
  modulesEdit_ = new QPlainTextEdit(selection);
  modulesEdit_->setPlaceholderText(
      QStringLiteral("每行一个模块 / One module per line\n:app:checkout"));
  modulesEdit_->setMaximumHeight(115);
  auto *classColumn = new QVBoxLayout;
  classColumn->addWidget(new QLabel(QStringLiteral("类 / Classes"), selection));
  classColumn->addWidget(classesEdit_);
  auto *moduleColumn = new QVBoxLayout;
  moduleColumn->addWidget(new QLabel(QStringLiteral("模块 / Modules"), selection));
  moduleColumn->addWidget(modulesEdit_);
  selectionLayout->addLayout(classColumn, 1);
  selectionLayout->addLayout(moduleColumn, 1);
  auto *optionsColumn = new QVBoxLayout;
  dependenciesCheck_ =
      new QCheckBox(QStringLiteral("包含唯一依赖\nInclude dependencies"), selection);
  forceCheck_ =
      new QCheckBox(QStringLiteral("替换已生成文件\nReplace generated files"), selection);
  optionsColumn->addWidget(dependenciesCheck_);
  optionsColumn->addWidget(forceCheck_);
  optionsColumn->addStretch();
  selectionLayout->addLayout(optionsColumn);
  layout->addWidget(selection);

  auto *binding =
      new QGroupBox(QStringLiteral("模块绑定 / Module binding"), content);
  auto *bindingForm = new QFormLayout(binding);
  applicationIdEdit_ =
      new QLineEdit(QStringLiteral("com.example.existingapp"), binding);
  moduleIdEdit_ = new QLineEdit(QStringLiteral("migration.module"), binding);
  channelEdit_ = new QLineEdit(QStringLiteral("enterprise"), binding);
  platformCombo_ = new QComboBox(binding);
  platformCombo_->addItems(
      {QStringLiteral("android"), QStringLiteral("ios"),
       QStringLiteral("harmonyos")});
  profileCombo_ = new QComboBox(binding);
  profileCombo_->addItems(
      {QStringLiteral("offline_sealed"),
       QStringLiteral("online_provisioned"),
       QStringLiteral("store_on_demand"),
       QStringLiteral("enterprise_managed")});
  releaseSpin_ = new QSpinBox(binding);
  releaseSpin_->setRange(1, 2147483647);
  releaseSpin_->setValue(1);
  bindingForm->addRow(QStringLiteral("Application ID"), applicationIdEdit_);
  bindingForm->addRow(QStringLiteral("Module ID"), moduleIdEdit_);
  bindingForm->addRow(QStringLiteral("Channel"), channelEdit_);
  bindingForm->addRow(QStringLiteral("Platform"), platformCombo_);
  bindingForm->addRow(QStringLiteral("Profile"), profileCombo_);
  bindingForm->addRow(QStringLiteral("Release"), releaseSpin_);
  layout->addWidget(binding);

  auto *strict =
      new QGroupBox(QStringLiteral("严格验证 / Strict verification"), content);
  auto *strictForm = new QFormLayout(strict);
  const QString bundledRuntime =
      QDir(QCoreApplication::applicationDirPath())
          .absoluteFilePath(QStringLiteral("../Resources/bin/pvm_cli"));
  runtimeEdit_ = new QLineEdit(
      QFileInfo(bundledRuntime).isExecutable()
          ? bundledRuntime
          : QDir(repoRoot_).filePath(QStringLiteral("build/client/pvm_cli")),
      strict);
  privateKeyEdit_ = new QLineEdit(
      QDir(repoRoot_).filePath(
          QStringLiteral("server/var/keys/dev-private.pem")),
      strict);
  publicKeyEdit_ = new QLineEdit(
      QDir(repoRoot_).filePath(
          QStringLiteral("server/var/keys/dev-public.pem")),
      strict);
  strictForm->addRow(
      QStringLiteral("C++17 Runtime"),
      pathField(runtimeEdit_, QStringLiteral("选择… / Browse"), [this] {
        chooseFile(runtimeEdit_, QStringLiteral("选择 pvm_cli / Select pvm_cli"));
      }));
  strictForm->addRow(
      QStringLiteral("Private key"),
      pathField(privateKeyEdit_, QStringLiteral("选择… / Browse"), [this] {
        chooseFile(privateKeyEdit_, QStringLiteral("选择私钥 / Select private key"));
      }));
  strictForm->addRow(
      QStringLiteral("Public key"),
      pathField(publicKeyEdit_, QStringLiteral("选择… / Browse"), [this] {
        chooseFile(publicKeyEdit_, QStringLiteral("选择公钥 / Select public key"));
      }));
  layout->addWidget(strict);

  auto *actions = new QHBoxLayout;
  scanButton_ = new QPushButton(QStringLiteral("1. 扫描 / Scan"), content);
  convertButton_ = new QPushButton(QStringLiteral("2. 生成 / Convert"), content);
  convertButton_->setObjectName(QStringLiteral("primary"));
  structuralButton_ =
      new QPushButton(QStringLiteral("3. 结构验证 / Verify"), content);
  strictButton_ =
      new QPushButton(QStringLiteral("4. 严格验证 / Strict"), content);
  cancelButton_ = new QPushButton(QStringLiteral("取消 / Cancel"), content);
  cancelButton_->setObjectName(QStringLiteral("danger"));
  cancelButton_->setEnabled(false);
  auto *openButton =
      new QPushButton(QStringLiteral("打开输出 / Open output"), content);
  actions->addWidget(scanButton_);
  actions->addWidget(convertButton_);
  actions->addWidget(structuralButton_);
  actions->addWidget(strictButton_);
  actions->addStretch();
  actions->addWidget(cancelButton_);
  actions->addWidget(openButton);
  layout->addLayout(actions);

  progress_ = new QProgressBar(content);
  progress_->setRange(0, 100);
  progress_->setValue(0);
  progress_->setFormat(QStringLiteral("%p%"));
  statusLabel_ = new QLabel(QStringLiteral("就绪 / Ready"), content);
  layout->addWidget(progress_);
  layout->addWidget(statusLabel_);
  layout->addStretch();

  connect(scanButton_, &QPushButton::clicked, this,
          [this] { start(Operation::Scan); });
  connect(convertButton_, &QPushButton::clicked, this,
          [this] { start(Operation::Convert); });
  connect(structuralButton_, &QPushButton::clicked, this,
          [this] { start(Operation::StructuralVerify); });
  connect(strictButton_, &QPushButton::clicked, this,
          [this] { start(Operation::StrictVerify); });
  connect(cancelButton_, &QPushButton::clicked, this,
          [this] { cancel(); });
  connect(openButton, &QPushButton::clicked, this,
          [this] { openOutput(); });

  scroll->setWidget(content);
  pageLayout->addWidget(scroll);
  return page;
}

QWidget *MigrationStudioWindow::buildReviewTab() {
  auto *page = new QWidget;
  auto *layout = new QVBoxLayout(page);
  layout->setContentsMargins(18, 16, 18, 16);
  layout->setSpacing(10);

  auto *help = new QLabel(
      QStringLiteral("直接编辑迁移审批、Capability、行为用例和 DSL。保存时会先校验 JSON；"
                     "module.pvm.json 还会通过 DSL 编译与 Host IDL 校验。\n"
                     "Edit review decisions, behavior cases and DSL directly. JSON is "
                     "validated before saving; DSL also passes compiler and Host IDL checks."),
      page);
  help->setWordWrap(true);
  layout->addWidget(help);

  auto *toolbar = new QHBoxLayout;
  reviewFileCombo_ = new QComboBox(page);
  reviewFileCombo_->addItems(
      {QStringLiteral("migration-approvals.json"),
       QStringLiteral("capabilities.json"),
       QStringLiteral("migration-cases.json"),
       QStringLiteral("module.pvm.json"),
       QStringLiteral("migration-report.json"),
       QStringLiteral("verification.json")});
  auto *reload = new QPushButton(QStringLiteral("重新载入 / Reload"), page);
  reviewSaveButton_ = new QPushButton(QStringLiteral("保存 / Save"), page);
  reviewSaveButton_->setObjectName(QStringLiteral("primary"));
  toolbar->addWidget(reviewFileCombo_, 1);
  toolbar->addWidget(reload);
  toolbar->addWidget(reviewSaveButton_);
  layout->addLayout(toolbar);

  reviewEditor_ = new QPlainTextEdit(page);
  reviewEditor_->setFont(QFontDatabase::systemFont(QFontDatabase::FixedFont));
  reviewEditor_->setLineWrapMode(QPlainTextEdit::NoWrap);
  layout->addWidget(reviewEditor_, 1);
  reviewStatus_ = new QLabel(QStringLiteral("尚未载入 / Not loaded"), page);
  layout->addWidget(reviewStatus_);

  connect(reviewFileCombo_, &QComboBox::currentTextChanged, this,
          [this] { reloadReview(); });
  connect(reload, &QPushButton::clicked, this, [this] { reloadReview(); });
  connect(reviewSaveButton_, &QPushButton::clicked, this,
          [this] { saveReview(); });
  return page;
}

QWidget *MigrationStudioWindow::buildLogTab() {
  auto *page = new QWidget;
  auto *layout = new QVBoxLayout(page);
  layout->setContentsMargins(18, 16, 18, 16);
  layout->setSpacing(10);

  auto *toolbar = new QHBoxLayout;
  auto *clear = new QPushButton(QStringLiteral("清空 / Clear"), page);
  auto *copy = new QPushButton(QStringLiteral("复制 / Copy"), page);
  auto *exportButton = new QPushButton(QStringLiteral("导出 / Export"), page);
  toolbar->addStretch();
  toolbar->addWidget(clear);
  toolbar->addWidget(copy);
  toolbar->addWidget(exportButton);
  layout->addLayout(toolbar);

  logEdit_ = new QPlainTextEdit(page);
  logEdit_->setReadOnly(true);
  logEdit_->setMaximumBlockCount(5000);
  logEdit_->setLineWrapMode(QPlainTextEdit::NoWrap);
  logEdit_->setFont(QFontDatabase::systemFont(QFontDatabase::FixedFont));
  layout->addWidget(logEdit_, 1);

  connect(clear, &QPushButton::clicked, logEdit_, &QPlainTextEdit::clear);
  connect(copy, &QPushButton::clicked, logEdit_, &QPlainTextEdit::copy);
  connect(exportButton, &QPushButton::clicked, this,
          [this] { exportLog(); });
  return page;
}

void MigrationStudioWindow::chooseSource() {
  const QString value = QFileDialog::getExistingDirectory(
      this, QStringLiteral("选择老项目 / Select legacy project"),
      sourceEdit_->text().isEmpty() ? repoRoot_ : sourceEdit_->text());
  if (!value.isEmpty()) {
    sourceEdit_->setText(value);
  }
}

void MigrationStudioWindow::chooseOutput() {
  const QString value = QFileDialog::getExistingDirectory(
      this, QStringLiteral("选择输出目录 / Select output directory"),
      outputEdit_->text());
  if (!value.isEmpty()) {
    outputEdit_->setText(value);
    reloadReview();
  }
}

void MigrationStudioWindow::chooseFile(QLineEdit *target,
                                       const QString &caption) {
  const QString value =
      QFileDialog::getOpenFileName(this, caption, target->text());
  if (!value.isEmpty()) {
    target->setText(value);
  }
}

QStringList MigrationStudioWindow::selectorArguments() const {
  QStringList arguments;
  for (const QString &value : studio::splitSelectors(classesEdit_->toPlainText())) {
    arguments << QStringLiteral("--class") << value;
  }
  for (const QString &value : studio::splitSelectors(modulesEdit_->toPlainText())) {
    arguments << QStringLiteral("--module") << value;
  }
  if (dependenciesCheck_->isChecked()) {
    arguments << QStringLiteral("--include-dependencies");
  }
  return arguments;
}

bool MigrationStudioWindow::validate(Operation operation, QString *error) const {
  const QString source = cleanAbsolutePath(sourceEdit_->text());
  const QString output = cleanAbsolutePath(outputEdit_->text());
  if (!QFileInfo(source).isDir()) {
    *error = QStringLiteral("请选择存在的老项目目录。/ Select an existing source directory.");
    return false;
  }
  if (outputEdit_->text().trimmed().isEmpty()) {
    *error = QStringLiteral("请选择输出目录。/ Select an output directory.");
    return false;
  }
  const QString prefix = source + QDir::separator();
  if (output == source || output.startsWith(prefix)) {
    *error = QStringLiteral("输出目录必须位于老项目之外。/ Output must be outside the source.");
    return false;
  }
  if (!QFileInfo(pythonEdit_->text()).isExecutable()) {
    *error = QStringLiteral("请选择可执行的 Python。/ Select an executable Python.");
    return false;
  }
  if (operation == Operation::Convert &&
      studio::splitSelectors(classesEdit_->toPlainText()).isEmpty() &&
      studio::splitSelectors(modulesEdit_->toPlainText()).isEmpty()) {
    *error = QStringLiteral("生成迁移骨架前至少选择一个类或模块。/"
                            "Select at least one class or module before conversion.");
    return false;
  }
  if (operation == Operation::Convert &&
      (applicationIdEdit_->text().trimmed().isEmpty() ||
       moduleIdEdit_->text().trimmed().isEmpty() ||
       channelEdit_->text().trimmed().isEmpty())) {
    *error = QStringLiteral("模块绑定字段不能为空。/ Module binding fields are required.");
    return false;
  }
  if ((operation == Operation::StructuralVerify ||
       operation == Operation::StrictVerify) &&
      !QFileInfo(QDir(output).filePath(QStringLiteral("migration-report.json")))
           .isFile()) {
    *error = QStringLiteral("输出目录中没有 migration-report.json，请先生成。/"
                            "Generate the migration output before verification.");
    return false;
  }
  if (operation == Operation::StrictVerify &&
      (!QFileInfo(runtimeEdit_->text()).isExecutable() ||
       !QFileInfo(privateKeyEdit_->text()).isFile() ||
       !QFileInfo(publicKeyEdit_->text()).isFile())) {
    *error = QStringLiteral("严格验证需要 pvm_cli 和开发密钥；请先运行 make bootstrap build。/"
                            "Strict verification requires pvm_cli and development keys.");
    return false;
  }
  return true;
}

QStringList MigrationStudioWindow::commandArguments(Operation operation) const {
  const QString source = cleanAbsolutePath(sourceEdit_->text());
  const QString output = cleanAbsolutePath(outputEdit_->text());
  QStringList arguments{QStringLiteral("-m"),
                        QStringLiteral("pvm_server.migrate")};
  if (operation == Operation::Scan) {
    const QFileInfo outputInfo(output);
    const QString scanReport = outputInfo.dir().filePath(
        outputInfo.fileName() + QStringLiteral("-scan.json"));
    arguments << QStringLiteral("scan") << source;
    arguments << selectorArguments();
    arguments << QStringLiteral("--output") << scanReport
              << QStringLiteral("--force") << QStringLiteral("--events-jsonl");
    return arguments;
  }
  if (operation == Operation::Convert) {
    arguments << QStringLiteral("convert") << source;
    arguments << selectorArguments();
    arguments << QStringLiteral("--application-id")
              << applicationIdEdit_->text().trimmed()
              << QStringLiteral("--platform") << platformCombo_->currentText()
              << QStringLiteral("--profile") << profileCombo_->currentText()
              << QStringLiteral("--module-id")
              << moduleIdEdit_->text().trimmed() << QStringLiteral("--channel")
              << channelEdit_->text().trimmed() << QStringLiteral("--release")
              << QString::number(releaseSpin_->value())
              << QStringLiteral("--output") << output;
    if (forceCheck_->isChecked()) {
      arguments << QStringLiteral("--force");
    }
    arguments << QStringLiteral("--events-jsonl");
    return arguments;
  }

  arguments << QStringLiteral("verify") << output << QStringLiteral("--source")
            << source;
  if (operation == Operation::StrictVerify) {
    arguments << QStringLiteral("--strict") << QStringLiteral("--runtime")
              << cleanAbsolutePath(runtimeEdit_->text())
              << QStringLiteral("--private-key")
              << cleanAbsolutePath(privateKeyEdit_->text())
              << QStringLiteral("--public-key")
              << cleanAbsolutePath(publicKeyEdit_->text());
  }
  arguments << QStringLiteral("--events-jsonl");
  return arguments;
}

QProcessEnvironment MigrationStudioWindow::processEnvironment() const {
  QProcessEnvironment environment = QProcessEnvironment::systemEnvironment();
  const QString bundledSource =
      QDir(QCoreApplication::applicationDirPath())
          .absoluteFilePath(QStringLiteral("../Resources/python"));
  const QString serverSource =
      QFileInfo(QDir(bundledSource)
                    .filePath(QStringLiteral("pvm_server/migrate.py")))
              .isFile()
          ? bundledSource
          : QDir(repoRoot_).filePath(QStringLiteral("server/src"));
  const QString current = environment.value(QStringLiteral("PYTHONPATH"));
  environment.insert(
      QStringLiteral("PYTHONPATH"),
      current.isEmpty()
          ? serverSource
          : serverSource + QDir::listSeparator() + current);
  environment.insert(QStringLiteral("PYTHONUNBUFFERED"), QStringLiteral("1"));
  environment.insert(QStringLiteral("PYTHONDONTWRITEBYTECODE"),
                     QStringLiteral("1"));
  return environment;
}

QString MigrationStudioWindow::hostIdlPath() const {
  const QString bundled =
      QDir(QCoreApplication::applicationDirPath())
          .absoluteFilePath(QStringLiteral("../spec/host_idl.json"));
  return QFileInfo(bundled).isFile()
             ? bundled
             : QDir(repoRoot_).filePath(QStringLiteral("spec/host_idl.json"));
}

void MigrationStudioWindow::start(Operation operation) {
  if (process_ != nullptr && process_->state() != QProcess::NotRunning) {
    return;
  }
  QString error;
  if (!validate(operation, &error)) {
    QMessageBox::warning(this, QStringLiteral("无法开始 / Cannot start"), error);
    return;
  }

  operation_ = operation;
  stdoutBuffer_.clear();
  stderrBuffer_.clear();
  progress_->setValue(0);
  statusLabel_->setText(operationName(operation) + QStringLiteral("…"));
  setRunning(true);
  tabs_->setCurrentIndex(2);

  process_ = new QProcess(this);
  process_->setProcessEnvironment(processEnvironment());
  process_->setProcessChannelMode(QProcess::SeparateChannels);
  connect(process_, &QProcess::readyReadStandardOutput, this,
          [this] { readStdout(); });
  connect(process_, &QProcess::readyReadStandardError, this,
          [this] { readStderr(); });
  connect(process_, &QProcess::finished, this,
          [this](int code, QProcess::ExitStatus status) {
            processFinished(code, status);
          });
  connect(process_, &QProcess::errorOccurred, this,
          [this](QProcess::ProcessError errorValue) {
            if (errorValue == QProcess::FailedToStart) {
              appendLog(QStringLiteral("ERROR"),
                        QStringLiteral("无法启动迁移进程 / Failed to start process"));
            }
          });

  const QStringList arguments = commandArguments(operation);
  appendLog(QStringLiteral("INFO"), operationName(operation));
  appendLog(QStringLiteral("COMMAND"),
            compactCommand(pythonEdit_->text(), arguments));
  process_->start(pythonEdit_->text(), arguments, QIODevice::ReadOnly);
}

void MigrationStudioWindow::cancel() {
  if (process_ == nullptr || process_->state() == QProcess::NotRunning) {
    return;
  }
  appendLog(QStringLiteral("WARN"),
            QStringLiteral("正在取消任务… / Cancelling task…"));
  process_->terminate();
  QPointer<QProcess> guarded(process_);
  QTimer::singleShot(3000, this, [guarded] {
    if (guarded && guarded->state() != QProcess::NotRunning) {
      guarded->kill();
    }
  });
}

void MigrationStudioWindow::setRunning(bool running) {
  scanButton_->setEnabled(!running);
  convertButton_->setEnabled(!running);
  structuralButton_->setEnabled(!running);
  strictButton_->setEnabled(!running);
  cancelButton_->setEnabled(running);
  reviewSaveButton_->setEnabled(
      !running &&
      studio::isEditableReviewFile(reviewFileCombo_->currentText()));
}

void MigrationStudioWindow::readStdout() {
  if (process_ != nullptr) {
    consumeLines(&stdoutBuffer_, process_->readAllStandardOutput(), true);
  }
}

void MigrationStudioWindow::readStderr() {
  if (process_ != nullptr) {
    consumeLines(&stderrBuffer_, process_->readAllStandardError(), false);
  }
}

void MigrationStudioWindow::consumeLines(QByteArray *buffer,
                                         const QByteArray &incoming,
                                         bool events) {
  buffer->append(incoming);
  qsizetype newline = -1;
  while ((newline = buffer->indexOf('\n')) >= 0) {
    const QByteArray line = buffer->left(newline).trimmed();
    buffer->remove(0, newline + 1);
    if (line.isEmpty()) {
      continue;
    }
    if (events) {
      handleEventLine(line);
    } else {
      appendLog(QStringLiteral("ERROR"), QString::fromUtf8(line));
    }
  }
}

void MigrationStudioWindow::handleEventLine(const QByteArray &line) {
  QJsonParseError parseError;
  const QJsonDocument document = QJsonDocument::fromJson(line, &parseError);
  if (parseError.error != QJsonParseError::NoError || !document.isObject()) {
    appendLog(QStringLiteral("INFO"), QString::fromUtf8(line));
    return;
  }
  const QJsonObject event = document.object();
  if (event.value(QStringLiteral("type")).toString() !=
      QStringLiteral("migration.event")) {
    appendLog(QStringLiteral("INFO"), QString::fromUtf8(line));
    return;
  }
  const QString stage = event.value(QStringLiteral("stage")).toString();
  const QString status = event.value(QStringLiteral("status")).toString();
  const QString message = event.value(QStringLiteral("message")).toString();
  const int progress = event.value(QStringLiteral("progress")).toInt();
  progress_->setValue(std::clamp(progress, 0, 100));
  statusLabel_->setText(studio::stageLabel(stage) + QStringLiteral(" — ") +
                        message);

  QString level = QStringLiteral("INFO");
  if (status == QStringLiteral("pass")) {
    level = QStringLiteral("SUCCESS");
  } else if (status == QStringLiteral("fail")) {
    level = QStringLiteral("ERROR");
  }
  appendLog(level, studio::stageLabel(stage) + QStringLiteral(" — ") + message);
  const QJsonObject details =
      event.value(QStringLiteral("details")).toObject();
  const QString detailError = details.value(QStringLiteral("error")).toString();
  if (!detailError.isEmpty()) {
    appendLog(QStringLiteral("ERROR"), detailError);
  }
  const QJsonObject artifacts =
      details.value(QStringLiteral("artifacts")).toObject();
  for (auto item = artifacts.constBegin(); item != artifacts.constEnd(); ++item) {
    appendLog(QStringLiteral("INFO"),
              item.key() + QStringLiteral(": ") + item.value().toString());
  }
  for (const QString &key :
       {QStringLiteral("report"), QStringLiteral("verification")}) {
    const QString path = details.value(key).toString();
    if (!path.isEmpty()) {
      appendLog(QStringLiteral("INFO"), key + QStringLiteral(": ") + path);
    }
  }
}

void MigrationStudioWindow::processFinished(
    int exitCode, QProcess::ExitStatus exitStatus) {
  if (!stdoutBuffer_.trimmed().isEmpty()) {
    handleEventLine(stdoutBuffer_.trimmed());
  }
  if (!stderrBuffer_.trimmed().isEmpty()) {
    appendLog(QStringLiteral("ERROR"), QString::fromUtf8(stderrBuffer_.trimmed()));
  }
  stdoutBuffer_.clear();
  stderrBuffer_.clear();

  const bool passed =
      exitStatus == QProcess::NormalExit && exitCode == 0;
  if (passed) {
    progress_->setValue(100);
    statusLabel_->setText(operationName(operation_) +
                          QStringLiteral("：完成 / Completed"));
    appendLog(QStringLiteral("SUCCESS"),
              operationName(operation_) + QStringLiteral(" completed"));
    if (operation_ == Operation::Convert ||
        operation_ == Operation::StructuralVerify ||
        operation_ == Operation::StrictVerify) {
      reloadReview();
    }
  } else {
    statusLabel_->setText(operationName(operation_) +
                          QStringLiteral("：失败 / Failed"));
    appendLog(QStringLiteral("ERROR"),
              QStringLiteral("进程退出码 / Exit code: %1").arg(exitCode));
  }
  operation_ = Operation::None;
  setRunning(false);
  process_->deleteLater();
  process_ = nullptr;
}

void MigrationStudioWindow::appendLog(const QString &level,
                                      const QString &message) {
  QTextCharFormat format;
  if (level == QStringLiteral("ERROR")) {
    format.setForeground(QColor(QStringLiteral("#ff7d90")));
  } else if (level == QStringLiteral("WARN")) {
    format.setForeground(QColor(QStringLiteral("#ffc861")));
  } else if (level == QStringLiteral("SUCCESS")) {
    format.setForeground(QColor(QStringLiteral("#64e6ad")));
  } else if (level == QStringLiteral("COMMAND")) {
    format.setForeground(QColor(QStringLiteral("#9bb7ff")));
  } else {
    format.setForeground(QColor(QStringLiteral("#9db4cf")));
  }
  QTextCursor cursor = logEdit_->textCursor();
  cursor.movePosition(QTextCursor::End);
  const QString prefix =
      QStringLiteral("[%1] [%2] ")
          .arg(QDateTime::currentDateTime().toString(QStringLiteral("HH:mm:ss")),
               level);
  cursor.insertText(prefix + safeForLog(message) + QLatin1Char('\n'), format);
  logEdit_->setTextCursor(cursor);
  logEdit_->ensureCursorVisible();
}

QString MigrationStudioWindow::safeForLog(QString message) const {
  const QString source = cleanAbsolutePath(sourceEdit_->text());
  const QString output = cleanAbsolutePath(outputEdit_->text());
  if (!sourceEdit_->text().trimmed().isEmpty()) {
    message.replace(source, QStringLiteral("<source>"));
  }
  if (!outputEdit_->text().trimmed().isEmpty()) {
    message.replace(output, QStringLiteral("<output>"));
  }
  message.replace(repoRoot_, QStringLiteral("<project>"));
  message.replace(QDir::homePath(), QStringLiteral("<home>"));
  return message;
}

QString MigrationStudioWindow::selectedReviewPath() const {
  return QDir(cleanAbsolutePath(outputEdit_->text()))
      .filePath(reviewFileCombo_->currentText());
}

void MigrationStudioWindow::reloadReview() {
  const QString path = selectedReviewPath();
  const bool editable =
      studio::isEditableReviewFile(reviewFileCombo_->currentText());
  reviewEditor_->setReadOnly(!editable);
  reviewSaveButton_->setEnabled(
      editable &&
      (process_ == nullptr || process_->state() == QProcess::NotRunning));
  QFile file(path);
  if (!file.open(QIODevice::ReadOnly)) {
    reviewEditor_->clear();
    reviewStatus_->setText(
        QStringLiteral("文件不存在 / File not found: %1").arg(path));
    return;
  }
  reviewEditor_->setPlainText(QString::fromUtf8(file.readAll()));
  reviewStatus_->setText(QStringLiteral("已载入 / Loaded: %1").arg(path));
}

void MigrationStudioWindow::saveReview() {
  if (!studio::isEditableReviewFile(reviewFileCombo_->currentText())) {
    QMessageBox::information(
        this, QStringLiteral("只读文件 / Read-only file"),
        QStringLiteral("报告和验证结果由工具生成，不能在复核页修改。/"
                       "Reports and verification results are generated."));
    return;
  }
  const QByteArray source = reviewEditor_->toPlainText().toUtf8();
  QJsonParseError parseError;
  const QJsonDocument document = QJsonDocument::fromJson(source, &parseError);
  if (parseError.error != QJsonParseError::NoError || !document.isObject()) {
    QMessageBox::warning(
        this, QStringLiteral("JSON 无效 / Invalid JSON"),
        QStringLiteral("%1，offset %2")
            .arg(parseError.errorString())
            .arg(parseError.offset));
    return;
  }
  const QString path = selectedReviewPath();
  if (!QFileInfo::exists(path)) {
    QMessageBox::warning(
        this, QStringLiteral("无法保存 / Cannot save"),
        QStringLiteral("迁移文件尚未生成。/ Migration file does not exist."));
    return;
  }
  const QByteArray encoded = document.toJson(QJsonDocument::Indented);

  if (reviewFileCombo_->currentText() == QStringLiteral("module.pvm.json")) {
    QTemporaryFile candidate(
        QDir(QFileInfo(path).absolutePath())
            .filePath(QStringLiteral(".pvm-studio-XXXXXX.json")));
    if (!candidate.open() || candidate.write(encoded) != encoded.size() ||
        !candidate.flush()) {
      QMessageBox::critical(this,
                            QStringLiteral("校验失败 / Validation failed"),
                            candidate.errorString());
      return;
    }
    const QString candidatePath = candidate.fileName();
    candidate.close();

    QProcess validator;
    validator.setProcessEnvironment(processEnvironment());
    validator.start(
        pythonEdit_->text(),
        {QStringLiteral("-m"), QStringLiteral("pvm_server.tooling"),
         QStringLiteral("lint"), candidatePath, QStringLiteral("--idl"),
         hostIdlPath()});
    if (!validator.waitForFinished(10000) ||
        validator.exitStatus() != QProcess::NormalExit ||
        validator.exitCode() != 0) {
      QMessageBox::critical(
          this, QStringLiteral("DSL 校验失败 / DSL validation failed"),
          safeForLog(QString::fromUtf8(validator.readAllStandardError())));
      return;
    }
  }

  QSaveFile file(path);
  if (!file.open(QIODevice::WriteOnly) || file.write(encoded) != encoded.size() ||
      !file.commit()) {
    QMessageBox::critical(this, QStringLiteral("保存失败 / Save failed"),
                          file.errorString());
    return;
  }
  reviewStatus_->setText(QStringLiteral("已保存 / Saved: %1").arg(path));
  appendLog(QStringLiteral("SUCCESS"),
            QStringLiteral("Saved review file: %1").arg(path));
  reloadReview();
}

void MigrationStudioWindow::openOutput() {
  const QString path = cleanAbsolutePath(outputEdit_->text());
  if (!QFileInfo(path).isDir()) {
    QMessageBox::information(
        this, QStringLiteral("输出目录 / Output"),
        QStringLiteral("输出目录尚未生成。/ Output directory does not exist."));
    return;
  }
  QDesktopServices::openUrl(QUrl::fromLocalFile(path));
}

void MigrationStudioWindow::exportLog() {
  const QString directory =
      QFileInfo(cleanAbsolutePath(outputEdit_->text())).isDir()
          ? cleanAbsolutePath(outputEdit_->text())
          : QDir(repoRoot_).filePath(QStringLiteral("build"));
  const QString path = QFileDialog::getSaveFileName(
      this, QStringLiteral("导出日志 / Export log"),
      QDir(directory).filePath(QStringLiteral("migration-studio.log")),
      QStringLiteral("Log files (*.log);;All files (*)"));
  if (path.isEmpty()) {
    return;
  }
  QSaveFile file(path);
  const QByteArray encoded = logEdit_->toPlainText().toUtf8();
  if (!file.open(QIODevice::WriteOnly) || file.write(encoded) != encoded.size() ||
      !file.commit()) {
    QMessageBox::critical(this, QStringLiteral("导出失败 / Export failed"),
                          file.errorString());
  }
}
