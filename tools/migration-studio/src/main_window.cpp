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
#include <QFrame>
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

QString bundledResourceRoot() {
#if defined(Q_OS_MACOS)
  return QDir(QCoreApplication::applicationDirPath())
      .absoluteFilePath(QStringLiteral("../Resources"));
#else
  return QCoreApplication::applicationDirPath();
#endif
}

QString bundledExecutable(const QString &name) {
#if defined(Q_OS_WIN)
  return QDir(bundledResourceRoot())
      .filePath(QStringLiteral("bin/") + name + QStringLiteral(".exe"));
#else
  return QDir(bundledResourceRoot()).filePath(QStringLiteral("bin/") + name);
#endif
}

QString bundledSpec(const QString &name) {
#if defined(Q_OS_MACOS)
  return QDir(QCoreApplication::applicationDirPath())
      .filePath(QStringLiteral("../spec/") + name);
#else
  return QDir(bundledResourceRoot()).filePath(QStringLiteral("spec/") + name);
#endif
}

bool isRepoCheckout(const QString &path) {
  return QFileInfo(QDir(path).filePath(
                       QStringLiteral("server/src/pvm_server/migrate.py")))
             .isFile() &&
         QFileInfo(QDir(path).filePath(QStringLiteral("spec/host_idl.json")))
             .isFile();
}

QString discoverRepoRoot() {
  for (const QString &start :
       {QCoreApplication::applicationDirPath(), QDir::currentPath()}) {
    QDir directory(start);
    do {
      if (isRepoCheckout(directory.absolutePath())) {
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

void addLabeledField(QHBoxLayout *row, QWidget *parent, const QString &label,
                     QWidget *field, int stretch = 1) {
  auto *column = new QVBoxLayout;
  column->setSpacing(6);
  auto *caption = new QLabel(label, parent);
  caption->setObjectName(QStringLiteral("fieldLabel"));
  column->addWidget(caption);
  column->addWidget(field);
  row->addLayout(column, stretch);
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
  resize(1360, 820);
  setMinimumSize(1080, 720);
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
  layout->setContentsMargins(24, 20, 24, 20);
  layout->setSpacing(12);

  auto *header = new QFrame(central);
  header->setObjectName(QStringLiteral("headerCard"));
  auto *headerLayout = new QHBoxLayout(header);
  headerLayout->setContentsMargins(18, 14, 18, 14);
  headerLayout->setSpacing(14);
  auto *badge = new QLabel(QStringLiteral("PVM"), header);
  badge->setObjectName(QStringLiteral("brandBadge"));
  auto *heading = new QVBoxLayout;
  heading->setSpacing(2);
  auto *title = new QLabel(QStringLiteral("Migration Studio"), header);
  title->setObjectName(QStringLiteral("title"));
  auto *subtitle = new QLabel(
      QStringLiteral("选择性迁移 · 审批 · C++17 VM 严格验证"), header);
  subtitle->setObjectName(QStringLiteral("subtitle"));
  heading->addWidget(title);
  heading->addWidget(subtitle);
  auto *version = new QLabel(QStringLiteral("RUNTIME 5  ·  PVBC V5"), header);
  version->setObjectName(QStringLiteral("versionBadge"));
  headerLayout->addWidget(badge);
  headerLayout->addLayout(heading, 1);
  headerLayout->addWidget(version);
  layout->addWidget(header);

  tabs_ = new QTabWidget(central);
  tabs_->setDocumentMode(false);
  tabs_->addTab(buildMigrationTab(), QStringLiteral("迁移"));
  tabs_->addTab(buildReviewTab(), QStringLiteral("复核"));
  tabs_->addTab(buildLogTab(), QStringLiteral("日志"));
  layout->addWidget(tabs_, 1);
  setCentralWidget(central);

  setStyleSheet(QStringLiteral(R"(
    QMainWindow, QWidget { background: #f5f7fa; color: #101828; }
    QLabel, QCheckBox { background: transparent; }
    QFrame#headerCard { background: #ffffff; border: 1px solid #eaecf0;
                        border-radius: 14px; }
    QLabel#brandBadge { background: #101828; color: #ffffff; border-radius: 9px;
                        padding: 9px 11px; font-size: 14px; font-weight: 800; }
    QLabel#title { font-size: 23px; font-weight: 750; color: #101828; }
    QLabel#subtitle { color: #667085; }
    QLabel#versionBadge { background: #ecfdf3; color: #067647; border-radius: 10px;
                          padding: 6px 10px; font-size: 11px; font-weight: 700; }
    QLabel#fieldLabel { color: #344054; font-size: 12px; font-weight: 650; }
    QLabel#statusLabel { color: #475467; font-weight: 600; }
    QTabWidget::pane { border: 0; background: transparent; top: 2px; }
    QTabBar { background: #ffffff; border: 1px solid #eaecf0;
              border-radius: 10px; }
    QTabBar::tab { background: transparent; color: #667085; padding: 9px 22px;
                   margin: 0 2px; border-radius: 8px; font-weight: 650; }
    QTabBar::tab:hover { background: #eaecf0; color: #344054; }
    QTabBar::tab:selected { background: #e2f4f6; color: #0e606a; }
    QGroupBox { background: #ffffff; border: 1px solid #eaecf0; border-radius: 12px;
                margin-top: 0; padding: 38px 16px 14px 16px; font-weight: 600; }
    QGroupBox::title { subcontrol-origin: border; subcontrol-position: top left;
                       left: 16px; top: 13px; padding: 0; color: #101828;
                       background: transparent; font-size: 13px; font-weight: 750; }
    QLineEdit, QPlainTextEdit, QComboBox, QSpinBox {
      background: #f9fafb; color: #101828; border: 1px solid #d0d5dd;
      border-radius: 8px; padding: 7px 10px; selection-background-color: #b8e5eb;
      selection-color: #101828; min-height: 20px;
    }
    QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus {
      background: #ffffff; border: 1px solid #168c9b;
    }
    QComboBox QAbstractItemView { background: #ffffff; color: #111827;
                                  selection-background-color: #e2f4f6; }
    QPushButton { background: #ffffff; color: #344054; border: 1px solid #d0d5dd;
                  border-radius: 8px; padding: 8px 14px; font-weight: 650; }
    QPushButton:hover { background: #f9fafb; border-color: #98a2b3; }
    QPushButton:disabled { color: #98a2b3; background: #f9fafb; border-color: #eaecf0; }
    QPushButton#primary { background: #168c9b; color: #ffffff; border-color: #168c9b;
                          font-weight: 750; }
    QPushButton#primary:hover { background: #117681; }
    QPushButton#danger { background: #ffffff; color: #b42318; border-color: #fda29b; }
    QFrame#actionCard { background: #ffffff; border: 1px solid #eaecf0;
                        border-radius: 12px; }
    QProgressBar { background: #f2f4f7; color: #344054; border: 0;
                   border-radius: 4px; text-align: center; min-height: 8px;
                   max-height: 8px; }
    QProgressBar::chunk { background: #168c9b; border-radius: 4px; }
    QScrollArea { border: 0; background: transparent; }
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
  scroll->setAlignment(Qt::AlignHCenter | Qt::AlignTop);
  auto *content = new QWidget(scroll);
  content->setMaximumWidth(1420);
  auto *layout = new QVBoxLayout(content);
  layout->setContentsMargins(6, 8, 6, 12);
  layout->setSpacing(10);

  auto *paths = new QGroupBox(QStringLiteral("01  项目路径"), content);
  auto *pathsRow = new QHBoxLayout(paths);
  pathsRow->setSpacing(14);
  sourceEdit_ = new QLineEdit(paths);
  sourceEdit_->setPlaceholderText(QStringLiteral("/path/to/legacy-project"));
  const QString defaultOutput =
      isRepoCheckout(repoRoot_)
          ? QDir(repoRoot_).filePath(
                QStringLiteral("build/migration-studio-output"))
          : QDir(QStandardPaths::writableLocation(
                     QStandardPaths::DocumentsLocation))
                .filePath(QStringLiteral("PVM Migration Studio"));
  outputEdit_ = new QLineEdit(
      defaultOutput, paths);
  const QString packagedBackend =
      bundledExecutable(QStringLiteral("pvm_migration_backend"));
  pythonEdit_ = new QLineEdit(
      QFileInfo(packagedBackend).isExecutable()
          ? packagedBackend
          : QStandardPaths::findExecutable(QStringLiteral("python3")),
      paths);
  addLabeledField(
      pathsRow, paths,
      QStringLiteral("源码目录"),
      pathField(sourceEdit_, QStringLiteral("浏览…"), [this] {
        chooseSource();
      }),
      2);
  addLabeledField(
      pathsRow, paths,
      QStringLiteral("输出目录"),
      pathField(outputEdit_, QStringLiteral("浏览…"), [this] {
        chooseOutput();
      }),
      2);
  addLabeledField(
      pathsRow, paths,
      QStringLiteral("迁移引擎"),
      pathField(pythonEdit_, QStringLiteral("浏览…"), [this] {
        chooseFile(pythonEdit_,
                   QStringLiteral("选择迁移引擎 / Select migration engine"));
      }));
  layout->addWidget(paths);

  auto *selection =
      new QGroupBox(QStringLiteral("02  迁移范围"), content);
  auto *selectionLayout = new QHBoxLayout(selection);
  classesEdit_ = new QPlainTextEdit(selection);
  classesEdit_->setPlaceholderText(
      QStringLiteral("每行一个类 / One class per line\nCheckoutViewModel"));
  classesEdit_->setFixedHeight(74);
  modulesEdit_ = new QPlainTextEdit(selection);
  modulesEdit_->setPlaceholderText(
      QStringLiteral("每行一个模块 / One module per line\n:app:checkout"));
  modulesEdit_->setFixedHeight(74);
  auto *classColumn = new QVBoxLayout;
  auto *classLabel = new QLabel(QStringLiteral("类"), selection);
  classLabel->setObjectName(QStringLiteral("fieldLabel"));
  classColumn->addWidget(classLabel);
  classColumn->addWidget(classesEdit_);
  auto *moduleColumn = new QVBoxLayout;
  auto *moduleLabel = new QLabel(QStringLiteral("模块"), selection);
  moduleLabel->setObjectName(QStringLiteral("fieldLabel"));
  moduleColumn->addWidget(moduleLabel);
  moduleColumn->addWidget(modulesEdit_);
  selectionLayout->addLayout(classColumn, 1);
  selectionLayout->addLayout(moduleColumn, 1);
  auto *optionsColumn = new QVBoxLayout;
  dependenciesCheck_ =
      new QCheckBox(QStringLiteral("包含本地唯一依赖"), selection);
  forceCheck_ =
      new QCheckBox(QStringLiteral("覆盖已生成文件"), selection);
  optionsColumn->addWidget(dependenciesCheck_);
  optionsColumn->addWidget(forceCheck_);
  optionsColumn->addStretch();
  selectionLayout->addLayout(optionsColumn);
  layout->addWidget(selection);

  auto *binding =
      new QGroupBox(QStringLiteral("03  模块绑定"), content);
  auto *bindingRow = new QHBoxLayout(binding);
  bindingRow->setSpacing(12);
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
  addLabeledField(bindingRow, binding, QStringLiteral("应用 ID"),
                  applicationIdEdit_, 2);
  addLabeledField(bindingRow, binding, QStringLiteral("模块 ID"),
                  moduleIdEdit_, 2);
  addLabeledField(bindingRow, binding, QStringLiteral("渠道"), channelEdit_);
  addLabeledField(bindingRow, binding, QStringLiteral("平台"),
                  platformCombo_);
  addLabeledField(bindingRow, binding, QStringLiteral("交付 Profile"), profileCombo_,
                  2);
  addLabeledField(bindingRow, binding, QStringLiteral("版本"), releaseSpin_);
  layout->addWidget(binding);

  auto *strict =
      new QGroupBox(QStringLiteral("04  严格验证"), content);
  auto *strictRow = new QHBoxLayout(strict);
  strictRow->setSpacing(14);
  const QString bundledRuntime =
      bundledExecutable(QStringLiteral("pvm_cli"));
  const QString defaultPrivateKey =
      QDir(repoRoot_).filePath(QStringLiteral("server/var/keys/dev-private.pem"));
  const QString defaultPublicKey =
      QDir(repoRoot_).filePath(QStringLiteral("server/var/keys/dev-public.pem"));
#if defined(Q_OS_WIN)
  const QString developmentRuntime = QDir(repoRoot_).filePath(
      QStringLiteral("build/client/Release/pvm_cli.exe"));
#else
  const QString developmentRuntime =
      QDir(repoRoot_).filePath(QStringLiteral("build/client/pvm_cli"));
#endif
  runtimeEdit_ = new QLineEdit(
      QFileInfo(bundledRuntime).isExecutable()
          ? bundledRuntime
          : developmentRuntime,
      strict);
  privateKeyEdit_ = new QLineEdit(
      QFileInfo(defaultPrivateKey).isFile() ? defaultPrivateKey : QString(),
      strict);
  publicKeyEdit_ = new QLineEdit(
      QFileInfo(defaultPublicKey).isFile() ? defaultPublicKey : QString(),
      strict);
  addLabeledField(
      strictRow, strict,
      QStringLiteral("C++17 Runtime"),
      pathField(runtimeEdit_, QStringLiteral("浏览…"), [this] {
        chooseFile(runtimeEdit_, QStringLiteral("选择 pvm_cli / Select pvm_cli"));
      }));
  addLabeledField(
      strictRow, strict,
      QStringLiteral("私钥"),
      pathField(privateKeyEdit_, QStringLiteral("浏览…"), [this] {
        chooseFile(privateKeyEdit_, QStringLiteral("选择私钥 / Select private key"));
      }));
  addLabeledField(
      strictRow, strict,
      QStringLiteral("公钥"),
      pathField(publicKeyEdit_, QStringLiteral("浏览…"), [this] {
        chooseFile(publicKeyEdit_, QStringLiteral("选择公钥 / Select public key"));
      }));
  layout->addWidget(strict);

  auto *actionCard = new QFrame(content);
  actionCard->setObjectName(QStringLiteral("actionCard"));
  auto *actionCardLayout = new QVBoxLayout(actionCard);
  actionCardLayout->setContentsMargins(14, 12, 14, 12);
  actionCardLayout->setSpacing(10);
  auto *actions = new QHBoxLayout;
  scanButton_ = new QPushButton(QStringLiteral("扫描"), actionCard);
  convertButton_ = new QPushButton(QStringLiteral("生成迁移骨架"), actionCard);
  convertButton_->setObjectName(QStringLiteral("primary"));
  structuralButton_ =
      new QPushButton(QStringLiteral("结构验证"), actionCard);
  strictButton_ =
      new QPushButton(QStringLiteral("严格验证"), actionCard);
  cancelButton_ = new QPushButton(QStringLiteral("取消"), actionCard);
  cancelButton_->setObjectName(QStringLiteral("danger"));
  cancelButton_->setEnabled(false);
  auto *openButton =
      new QPushButton(QStringLiteral("打开输出目录"), actionCard);
  actions->addWidget(scanButton_);
  actions->addWidget(convertButton_);
  actions->addWidget(structuralButton_);
  actions->addWidget(strictButton_);
  actions->addStretch();
  actions->addWidget(cancelButton_);
  actions->addWidget(openButton);
  actionCardLayout->addLayout(actions);

  auto *progressRow = new QHBoxLayout;
  statusLabel_ = new QLabel(QStringLiteral("就绪"), actionCard);
  statusLabel_->setObjectName(QStringLiteral("statusLabel"));
  progress_ = new QProgressBar(actionCard);
  progress_->setRange(0, 100);
  progress_->setValue(0);
  progress_->setTextVisible(false);
  progressRow->addWidget(statusLabel_);
  progressRow->addWidget(progress_, 1);
  actionCardLayout->addLayout(progressRow);
  layout->addWidget(actionCard);
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
  layout->setContentsMargins(12, 12, 12, 12);
  layout->setSpacing(12);

  auto *help = new QLabel(
      QStringLiteral("复核迁移审批、Capability、行为用例和 DSL。JSON 保存前会校验，"
                     "DSL 还会经过编译器与 Host IDL 检查。"),
      page);
  help->setWordWrap(true);
  help->setObjectName(QStringLiteral("statusLabel"));
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
  auto *reload = new QPushButton(QStringLiteral("重新载入"), page);
  reviewSaveButton_ = new QPushButton(QStringLiteral("保存修改"), page);
  reviewSaveButton_->setObjectName(QStringLiteral("primary"));
  toolbar->addWidget(reviewFileCombo_, 1);
  toolbar->addWidget(reload);
  toolbar->addWidget(reviewSaveButton_);
  layout->addLayout(toolbar);

  reviewEditor_ = new QPlainTextEdit(page);
  reviewEditor_->setFont(QFontDatabase::systemFont(QFontDatabase::FixedFont));
  reviewEditor_->setLineWrapMode(QPlainTextEdit::NoWrap);
  layout->addWidget(reviewEditor_, 1);
  reviewStatus_ = new QLabel(QStringLiteral("尚未载入"), page);
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
  layout->setContentsMargins(12, 12, 12, 12);
  layout->setSpacing(12);

  auto *toolbar = new QHBoxLayout;
  auto *clear = new QPushButton(QStringLiteral("清空"), page);
  auto *copy = new QPushButton(QStringLiteral("复制"), page);
  auto *exportButton = new QPushButton(QStringLiteral("导出日志"), page);
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
    *error = QStringLiteral(
        "请选择可执行的迁移引擎。/ Select an executable migration engine.");
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
      QDir(bundledResourceRoot()).filePath(QStringLiteral("python"));
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
  environment.insert(QStringLiteral("PVM_HOST_IDL"), hostIdlPath());
  const QString packagedSigner = bundledExecutable(QStringLiteral("pvm_cli"));
  if (QFileInfo(packagedSigner).isExecutable()) {
    environment.insert(QStringLiteral("PVM_SIGNER"), packagedSigner);
  }
  return environment;
}

QString MigrationStudioWindow::hostIdlPath() const {
  const QString bundled = bundledSpec(QStringLiteral("host_idl.json"));
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
    format.setForeground(QColor(QStringLiteral("#b42318")));
  } else if (level == QStringLiteral("WARN")) {
    format.setForeground(QColor(QStringLiteral("#9a6700")));
  } else if (level == QStringLiteral("SUCCESS")) {
    format.setForeground(QColor(QStringLiteral("#067647")));
  } else if (level == QStringLiteral("COMMAND")) {
    format.setForeground(QColor(QStringLiteral("#175cd3")));
  } else {
    format.setForeground(QColor(QStringLiteral("#475467")));
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
