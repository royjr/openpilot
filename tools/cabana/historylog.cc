#include "tools/cabana/historylog.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <functional>

#include <QFileDialog>
#include <QPainter>
#include <QVBoxLayout>

#include "tools/cabana/commands.h"
#include "tools/cabana/utils/export.h"

namespace {

const std::array<uint16_t, 256> &crc16XmodemTable() {
  static const std::array<uint16_t, 256> table = [] {
    std::array<uint16_t, 256> lut = {};
    for (int i = 0; i < lut.size(); ++i) {
      uint16_t crc = i << 8;
      for (int bit = 0; bit < 8; ++bit) {
        crc = (crc & 0x8000) ? ((crc << 1) ^ 0x1021) : (crc << 1);
      }
      lut[i] = crc;
    }
    return lut;
  }();
  return table;
}

uint16_t hkgCanFdChecksum(uint32_t address, const std::vector<uint8_t> &data) {
  uint16_t crc = 0;
  const auto &lut = crc16XmodemTable();
  for (int i = 2; i < data.size(); ++i) {
    crc = ((crc << 8) ^ lut[(crc >> 8) ^ data[i]]) & 0xFFFF;
  }
  crc = ((crc << 8) ^ lut[(crc >> 8) ^ (address & 0xFF)]) & 0xFFFF;
  crc = ((crc << 8) ^ lut[(crc >> 8) ^ ((address >> 8) & 0xFF)]) & 0xFFFF;
  switch (data.size()) {
    case 8: crc ^= 0x5F29; break;
    case 16: crc ^= 0x041D; break;
    case 24: crc ^= 0x819D; break;
    case 32: crc ^= 0x9F5B; break;
    default: break;
  }
  return crc;
}

}  // namespace

QVariant HistoryLogModel::data(const QModelIndex &index, int role) const {
  if (!index.isValid() || index.row() >= messages.size()) return {};

  const auto &m = messages[index.row()];
  const int col = index.column();
  const int checksum_idx = checksumSignalIndex();
  const bool checksum_col = !isHexMode() && col > 0 && (col - 1) == checksum_idx;
  const auto checksum_valid = checksum_col ? checksumValid(index.row()) : std::optional<bool>{};
  if (m.missing_counter) {
    if (role == Qt::BackgroundRole) return QBrush(QColor(255, 255, 0, 96));
    if (role == Qt::TextAlignmentRole) return (uint32_t)(Qt::AlignRight | Qt::AlignVCenter);
    return {};
  }

  if (role == Qt::DisplayRole) {
    if (col == 0) return QString::number(can->toSeconds(m.mono_time), 'f', 3);
    if (!isHexMode()) {
      QString value = QString::fromStdString(sigs[col - 1]->formatValue(m.sig_values[col - 1], false));
      if (checksum_col && checksum_valid.has_value()) {
        return QString("%1 %2").arg(*checksum_valid ? QString::fromUtf8("\xE2\x9C\x93") : "x", value);
      }
      return value;
    }
  } else if (role == Qt::TextAlignmentRole) {
    return (uint32_t)(Qt::AlignRight | Qt::AlignVCenter);
  } else if (role == Qt::ForegroundRole && checksum_col && checksum_valid.has_value()) {
    return QColor(Qt::black);
  } else if (role == Qt::BackgroundRole && checksum_col && checksum_valid.has_value()) {
    return QBrush(*checksum_valid ? QColor(0, 255, 0, 96) : QColor(255, 0, 0, 96));
  } else if (role == Qt::BackgroundRole && hasImmediateDuplicateCounter(index.row())) {
    return QBrush(QColor(255, 0, 0, 96));
  }

  if (isHexMode() && col == 1) {
    if (role == ColorsRole) return QVariant::fromValue((void *)(&m.colors));
    if (role == BytesRole) return QVariant::fromValue((void *)(&m.data));
  }
  return {};
}

int HistoryLogModel::counterSignalIndex() const {
  auto it = std::find_if(sigs.cbegin(), sigs.cend(), [](const auto *sig) {
    return QString::compare(QString::fromStdString(sig->name), "counter", Qt::CaseInsensitive) == 0;
  });
  return it != sigs.cend() ? std::distance(sigs.cbegin(), it) : -1;
}

int HistoryLogModel::checksumSignalIndex() const {
  auto it = std::find_if(sigs.cbegin(), sigs.cend(), [](const auto *sig) {
    return QString::compare(QString::fromStdString(sig->name), "checksum", Qt::CaseInsensitive) == 0;
  });
  return it != sigs.cend() ? std::distance(sigs.cbegin(), it) : -1;
}

bool HistoryLogModel::hasImmediateDuplicateCounter(int row) const {
  const int counter_idx = counterSignalIndex();
  if (counter_idx < 0 || row <= 0 || row >= messages.size()) return false;
  if (messages[row].missing_counter || messages[row - 1].missing_counter) return false;
  return messages[row].sig_values[counter_idx] == messages[row - 1].sig_values[counter_idx];
}

std::optional<bool> HistoryLogModel::checksumValid(int row) const {
  const int checksum_idx = checksumSignalIndex();
  if (checksum_idx < 0 || row < 0 || row >= messages.size()) return std::nullopt;

  const auto &message = messages[row];
  if (message.missing_counter || message.data.empty()) return std::nullopt;

  const long long checksum = std::llround(message.sig_values[checksum_idx]);
  if (checksum < 0 || checksum > 0xFFFF) return std::nullopt;
  if (message.data.size() != 8 && message.data.size() != 16 && message.data.size() != 24 && message.data.size() != 32) {
    return std::nullopt;
  }
  return static_cast<uint16_t>(checksum) == hkgCanFdChecksum(msg_id.address, message.data);
}

const HistoryLogModel::Message *HistoryLogModel::firstActualMessage() const {
  auto it = std::find_if(messages.cbegin(), messages.cend(), [](const auto &message) { return !message.missing_counter; });
  return it != messages.cend() ? &(*it) : nullptr;
}

const HistoryLogModel::Message *HistoryLogModel::lastActualMessage() const {
  auto it = std::find_if(messages.crbegin(), messages.crend(), [](const auto &message) { return !message.missing_counter; });
  return it != messages.crend() ? &(*it) : nullptr;
}

void HistoryLogModel::setMessage(const MessageId &message_id) {
  msg_id = message_id;
  reset();
}

void HistoryLogModel::reset() {
  beginResetModel();
  sigs.clear();
  if (auto dbc_msg = dbc()->msg(msg_id)) {
    sigs = dbc_msg->getSignals();
  }
  messages.clear();
  hex_colors = {};
  endResetModel();
  setFilter(0, "", nullptr);
}

QVariant HistoryLogModel::headerData(int section, Qt::Orientation orientation, int role) const {
  if (orientation == Qt::Horizontal) {
    if (role == Qt::DisplayRole || role == Qt::ToolTipRole) {
      if (section == 0) return "Time";
      if (isHexMode()) return "Data";

      QString name = QString::fromStdString(sigs[section - 1]->name);
      QString unit = QString::fromStdString(sigs[section - 1]->unit);
      return unit.isEmpty() ? name : QString("%1 (%2)").arg(name, unit);
    } else if (role == Qt::BackgroundRole && section > 0 && !isHexMode()) {
      // Alpha-blend the signal color with the background to ensure contrast
      QColor sigColor = sigs[section - 1]->color;
      sigColor.setAlpha(128);
      return QBrush(sigColor);
    }
  }
  return {};
}

void HistoryLogModel::setHexMode(bool hex) {
  hex_mode = hex;
  reset();
}

void HistoryLogModel::setFilter(int sig_idx, const QString &value, std::function<bool(double, double)> cmp) {
  filter_sig_idx = sig_idx;
  filter_value = value.toDouble();
  filter_cmp = value.isEmpty() ? nullptr : cmp;
  updateState(true);
}

void HistoryLogModel::updateState(bool clear) {
  if (clear && !messages.empty()) {
    beginRemoveRows({}, 0, messages.size() - 1);
    messages.clear();
    endRemoveRows();
  }
  uint64_t current_time = can->toMonoTime(can->lastMessage(msg_id).ts) + 1;
  fetchData(messages.begin(), current_time, firstActualMessage() ? firstActualMessage()->mono_time : 0);
}

bool HistoryLogModel::canFetchMore(const QModelIndex &parent) const {
  const auto &events = can->events(msg_id);
  const Message *last_actual = lastActualMessage();
  return !events.empty() && last_actual && last_actual->mono_time > events.front()->mono_time;
}

void HistoryLogModel::fetchMore(const QModelIndex &parent) {
  if (const Message *last_actual = lastActualMessage()) {
    fetchData(messages.end(), last_actual->mono_time, 0);
  }
}

void HistoryLogModel::fetchData(std::deque<Message>::iterator insert_pos, uint64_t from_time, uint64_t min_time) {
  auto isIntegerValue = [](double value) {
    return std::isfinite(value) && std::fabs(value - std::llround(value)) < 1e-6;
  };
  auto buildMissingRows = [&](const Message &prev, const Message &next) {
    std::vector<Message> gap_rows;
    const int counter_idx = counterSignalIndex();
    if (counter_idx < 0 || prev.missing_counter || next.missing_counter) return gap_rows;

    const double prev_value = prev.sig_values[counter_idx];
    const double next_value = next.sig_values[counter_idx];
    if (!isIntegerValue(prev_value) || !isIntegerValue(next_value)) return gap_rows;

    const long long prev_counter = std::llround(prev_value);
    const long long next_counter = std::llround(next_value);
    if (prev_counter < 0 || prev_counter > 255 || next_counter < 0 || next_counter > 255) return gap_rows;

    const int forward_distance = (static_cast<int>(next_counter) - static_cast<int>(prev_counter) + 256) % 256;
    const int backward_distance = (static_cast<int>(prev_counter) - static_cast<int>(next_counter) + 256) % 256;
    const int step = forward_distance <= backward_distance ? 1 : -1;
    const int missing_count = std::min(forward_distance, backward_distance) - 1;
    if (missing_count <= 0) return gap_rows;

    int missing = static_cast<int>(prev_counter);
    for (int i = 0; i < missing_count; ++i) {
      missing = (missing + step + 256) % 256;
      gap_rows.emplace_back(Message{.missing_counter = true});
    }
    return gap_rows;
  };

  const auto &events = can->events(msg_id);
  auto first = std::upper_bound(events.rbegin(), events.rend(), from_time, [](uint64_t ts, auto e) {
    return ts > e->mono_time;
  });

  std::vector<HistoryLogModel::Message> actual_msgs;
  std::vector<double> values(sigs.size());
  actual_msgs.reserve(batch_size);
  for (; first != events.rend() && (*first)->mono_time > min_time; ++first) {
    const CanEvent *e = *first;
    for (int i = 0; i < sigs.size(); ++i) {
      sigs[i]->getValue(e->dat, e->size, &values[i]);
    }
    if (!filter_cmp || filter_cmp(values[filter_sig_idx], filter_value)) {
      actual_msgs.emplace_back(Message{e->mono_time, values, {e->dat, e->dat + e->size}});
      if (actual_msgs.size() >= batch_size && min_time == 0) {
        break;
      }
    }
  }

  if (!actual_msgs.empty()) {
    std::vector<HistoryLogModel::Message> msgs;
    msgs.reserve(actual_msgs.size());
    if (insert_pos != messages.begin()) {
      if (const Message *prev_actual = lastActualMessage()) {
        auto gap_rows = buildMissingRows(*prev_actual, actual_msgs.front());
        msgs.insert(msgs.end(), std::make_move_iterator(gap_rows.begin()), std::make_move_iterator(gap_rows.end()));
      }
    }
    msgs.push_back(actual_msgs.front());
    for (int i = 1; i < actual_msgs.size(); ++i) {
      auto gap_rows = buildMissingRows(actual_msgs[i - 1], actual_msgs[i]);
      msgs.insert(msgs.end(), std::make_move_iterator(gap_rows.begin()), std::make_move_iterator(gap_rows.end()));
      msgs.push_back(actual_msgs[i]);
    }
    if (insert_pos != messages.end()) {
      if (const Message *next_actual = firstActualMessage()) {
        auto gap_rows = buildMissingRows(actual_msgs.back(), *next_actual);
        msgs.insert(msgs.end(), std::make_move_iterator(gap_rows.begin()), std::make_move_iterator(gap_rows.end()));
      }
    }

    if (isHexMode() && (min_time > 0 || messages.empty())) {
      const auto freq = can->lastMessage(msg_id).freq;
      const std::vector<uint8_t> no_mask;
      for (auto &m : msgs) {
        if (m.missing_counter) continue;
        hex_colors.compute(msg_id, m.data.data(), m.data.size(), m.mono_time / (double)1e9, can->getSpeed(), no_mask, freq);
        m.colors = hex_colors.colors;
      }
    }
    int pos = std::distance(messages.begin(), insert_pos);
    beginInsertRows({}, pos , pos + msgs.size() - 1);
    messages.insert(insert_pos, std::move_iterator(msgs.begin()), std::move_iterator(msgs.end()));
    endInsertRows();
  }
}

// HeaderView

QSize HeaderView::sectionSizeFromContents(int logicalIndex) const {
  static const QSize time_col_size = fontMetrics().size(Qt::TextSingleLine, "000000.000") + QSize(10, 6);
  if (logicalIndex == 0) {
    return time_col_size;
  } else {
    int default_size = qMax(100, (rect().width() - time_col_size.width()) / (model()->columnCount() - 1));
    QString text = model()->headerData(logicalIndex, this->orientation(), Qt::DisplayRole).toString();
    const QRect rect = fontMetrics().boundingRect({0, 0, default_size, 2000}, defaultAlignment(), text.replace(QChar('_'), ' '));
    QSize size = rect.size() + QSize{10, 6};
    return QSize{qMax(size.width(), default_size), size.height()};
  }
}

void HeaderView::paintSection(QPainter *painter, const QRect &rect, int logicalIndex) const {
  auto bg_role = model()->headerData(logicalIndex, Qt::Horizontal, Qt::BackgroundRole);
  if (bg_role.isValid()) {
    painter->fillRect(rect, bg_role.value<QBrush>());
  }
  QString text = model()->headerData(logicalIndex, Qt::Horizontal, Qt::DisplayRole).toString();
  painter->setPen(palette().color(utils::isDarkTheme() ? QPalette::BrightText : QPalette::Text));
  painter->drawText(rect.adjusted(5, 3, -5, -3), defaultAlignment(), text.replace(QChar('_'), ' '));
}

// LogsWidget

LogsWidget::LogsWidget(QWidget *parent) : QFrame(parent) {
  setFrameStyle(QFrame::StyledPanel | QFrame::Plain);
  QVBoxLayout *main_layout = new QVBoxLayout(this);
  main_layout->setContentsMargins(0, 0, 0, 0);
  main_layout->setSpacing(0);

  QWidget *toolbar = new QWidget(this);
  toolbar->setAutoFillBackground(true);
  QHBoxLayout *h = new QHBoxLayout(toolbar);

  filters_widget = new QWidget(this);
  QHBoxLayout *filter_layout = new QHBoxLayout(filters_widget);
  filter_layout->setContentsMargins(0, 0, 0, 0);
  filter_layout->addWidget(display_type_cb = new QComboBox(this));
  filter_layout->addWidget(signals_cb = new QComboBox(this));
  filter_layout->addWidget(comp_box = new QComboBox(this));
  filter_layout->addWidget(value_edit = new QLineEdit(this));
  h->addWidget(filters_widget);
  h->addStretch(0);
  export_btn = new ToolButton("filetype-csv", tr("Export to CSV file..."));
  h->addWidget(export_btn, 0, Qt::AlignRight);

  display_type_cb->addItems({"Signal", "Hex"});
  display_type_cb->setToolTip(tr("Display signal value or raw hex value"));
  comp_box->addItems({">", "=", "!=", "<"});
  value_edit->setClearButtonEnabled(true);
  value_edit->setValidator(new DoubleValidator(this));

  main_layout->addWidget(toolbar);
  QFrame *line = new QFrame(this);
  line->setFrameStyle(QFrame::HLine | QFrame::Sunken);
  main_layout->addWidget(line);
  main_layout->addWidget(logs = new QTableView(this));
  logs->setModel(model = new HistoryLogModel(this));
  logs->setItemDelegate(delegate = new MessageBytesDelegate(this));
  logs->setHorizontalHeader(new HeaderView(Qt::Horizontal, this));
  logs->horizontalHeader()->setDefaultAlignment(Qt::AlignRight | (Qt::Alignment)Qt::TextWordWrap);
  logs->horizontalHeader()->setSectionResizeMode(QHeaderView::ResizeToContents);
  logs->verticalHeader()->setSectionResizeMode(QHeaderView::Fixed);
  logs->verticalHeader()->setDefaultSectionSize(delegate->sizeForBytes(8).height());
  logs->setFrameShape(QFrame::NoFrame);

  QObject::connect(display_type_cb, qOverload<int>(&QComboBox::activated), model, &HistoryLogModel::setHexMode);
  QObject::connect(signals_cb, SIGNAL(activated(int)), this, SLOT(filterChanged()));
  QObject::connect(comp_box, SIGNAL(activated(int)), this, SLOT(filterChanged()));
  QObject::connect(value_edit, &QLineEdit::textEdited, this, &LogsWidget::filterChanged);
  QObject::connect(export_btn, &QToolButton::clicked, this, &LogsWidget::exportToCSV);
  QObject::connect(can, &AbstractStream::seekedTo, model, &HistoryLogModel::reset);
  QObject::connect(dbc(), &DBCManager::DBCFileChanged, model, &HistoryLogModel::reset);
  QObject::connect(UndoStack::instance(), &QUndoStack::indexChanged, model, &HistoryLogModel::reset);
  QObject::connect(model, &HistoryLogModel::modelReset, this, &LogsWidget::modelReset);
  QObject::connect(model, &HistoryLogModel::rowsInserted, [this]() { export_btn->setEnabled(true); });
}

void LogsWidget::modelReset() {
  signals_cb->clear();
  for (auto s : model->sigs) {
    signals_cb->addItem(QString::fromStdString(s->name));
  }
  export_btn->setEnabled(false);
  value_edit->clear();
  comp_box->setCurrentIndex(0);
  filters_widget->setVisible(!model->sigs.empty());
}

void LogsWidget::filterChanged() {
  if (value_edit->text().isEmpty() && !value_edit->isModified()) return;

  std::function<bool(double, double)> cmp = nullptr;
  switch (comp_box->currentIndex()) {
    case 0: cmp = std::greater<double>{}; break;
    case 1: cmp = std::equal_to<double>{}; break;
    case 2: cmp = [](double l, double r) { return l != r; }; break; // not equal
    case 3: cmp = std::less<double>{}; break;
  }
  model->setFilter(signals_cb->currentIndex(), value_edit->text(), cmp);
}

void LogsWidget::exportToCSV() {
  QString dir = QString("%1/%2_%3.csv").arg(settings.last_dir).arg(QString::fromStdString(can->routeName())).arg(QString::fromStdString(msgName(model->msg_id)));
  QString fn = QFileDialog::getSaveFileName(this, QString("Export %1 to CSV file").arg(QString::fromStdString(msgName(model->msg_id))),
                                            dir, tr("csv (*.csv)"));
  if (!fn.isEmpty()) {
    model->isHexMode() ? utils::exportToCSV(fn, model->msg_id)
                       : utils::exportSignalsToCSV(fn, model->msg_id);
  }
}
