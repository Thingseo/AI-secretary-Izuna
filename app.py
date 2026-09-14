"""Izuna Desktop — Windows-first transparent desktop companion."""
from __future__ import annotations
import math
import random
import sys
import time
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import Qt, QTimer, QPoint, QRect, QSize, QLockFile, QStandardPaths, QUrl
from PySide6.QtGui import QPixmap, QPainter, QIcon, QRegion, QColor, QFont, QCursor, QAction, QTransform, QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout, QHBoxLayout, QPushButton,
    QScrollArea, QLineEdit, QPlainTextEdit, QDialog, QFormLayout, QCheckBox,
    QSpinBox, QDoubleSpinBox, QComboBox, QDialogButtonBox, QMessageBox, QMenu,
    QSystemTrayIcon, QFrame, QTabWidget, QTabBar, QInputDialog, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QListWidget, QListWidgetItem,
    QFileDialog, QStackedWidget, QSizePolicy,
)
from core import ASSETS, EMOTIONS, Store, KeyVault, build_payload, demo_reply, CHARACTERS, summary_target, build_summary_payload
from network import ChatClient, ModelCatalog
from providers import PROVIDERS, PRESETS, ollama_base
from stocks import MarketClient, position_values

STYLE = '''
QWidget { color: #e6edf5; font-family: "Malgun Gothic", "Noto Sans CJK KR", sans-serif; font-size: 13px; }
QDialog, QWidget#settingsPage, QWidget#chat, QWidget#stocks { background: #121e2b; }
QFrame#header { background: #182939; border-radius: 16px; }
QLabel#title { color: #f3faff; font-size: 21px; font-weight: 700; }
QLabel#muted { color: #9bb0c2; font-size: 11px; }
QLabel#badge { color: #77d8e6; background: #223d49; border-radius: 8px; padding: 4px 9px; font-size: 10px; }
QLabel#assistantBubble { color: #e6edf5; background: #203345; border-radius: 13px; padding: 12px; }
QLabel#userBubble { color: #102633; background: #a1e7ee; border-radius: 13px; padding: 12px; }
QLabel#notice { color: #adc1d0; background: #182735; border-radius: 9px; padding: 10px; font-size: 11px; }
QPushButton { background: #283d50; border: none; border-radius: 9px; padding: 8px 12px; }
QPushButton:hover { background: #34536a; }
QPushButton:pressed { background: #42647d; }
QPushButton:disabled { color: #6d8397; background: #1e2c3a; }
QPushButton#primary { color: #102632; background: #81dce8; font-weight: 700; }
QPushButton#primary:hover { background: #acecf3; }
QPushButton#chip { background: #192d3d; border: 1px solid #30495d; font-size: 11px; padding: 7px 9px; }
QPushButton#close { background: transparent; color: #9fb3c4; }
QPushButton#close:hover { background: #345b72; color: #ffffff; }
QPushButton#close:pressed { background: #4b7891; color: #ffffff; }
QPushButton#close:focus { border: 1px solid #81dce8; }
QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox { color: #e6edf5; background: #0e1925; border: 1px solid #344b61; border-radius: 8px; padding: 9px; selection-background-color: #3f637d; }
QLineEdit:focus, QPlainTextEdit:focus { border: 1px solid #77d8e6; }
QScrollArea { background: transparent; border: none; }
QScrollBar:vertical { background: transparent; width: 7px; margin: 0; }
QScrollBar::handle:vertical { background: #36526a; border-radius: 3px; min-height: 28px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
QComboBox QAbstractItemView { background: #142536; color: #e6edf5; selection-background-color: #365268; }
QCheckBox { spacing: 9px; padding: 5px; }
QCheckBox::indicator { width: 17px; height: 17px; }
QTabWidget::pane { border: none; }
QTabBar::tab { background: #1d3042; padding: 10px 18px; margin: 0 5px 12px 0; border-radius: 7px; }
QTabBar::tab:selected { background: #365268; color: #a2e9ef; }
QMenu { background: #172737; border: 1px solid #3a5266; padding: 6px; }
QMenu::item { padding: 7px 23px; border-radius: 5px; }
QMenu::item:selected { background: #355269; }
QTableWidget { background: #0e1925; border: 1px solid #344b61; border-radius: 8px; gridline-color: #263d50; }
QHeaderView::section { color: #a9bdcc; background: #182939; border: none; padding: 7px; }
QHeaderView, QTableCornerButton::section { background: #182939; border: none; }
'''


def button(text, callback, name=None):
    b = QPushButton(text)
    if name:
        b.setObjectName(name)
    b.setCursor(Qt.PointingHandCursor)
    b.clicked.connect(callback)
    return b


def label(text, name=None):
    w = QLabel(text)
    w.setTextFormat(Qt.PlainText)
    if name:
        w.setObjectName(name)
    return w


def clamp_position(pos, size, area):
    return QPoint(max(area.left(), min(pos.x(), area.right() - size.width() + 1)),
                  max(area.top(), min(pos.y(), area.bottom() - size.height() + 1)))


class SettingsDialog(QDialog):
    def __init__(self, controller):
        super().__init__(controller.chat)
        self.c = controller
        s = controller.store.effective_settings
        self.setWindowTitle(CHARACTERS[controller.store.character]['name'] + ' · 설정')
        self.resize(570, 690)
        self.setMinimumWidth(480)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 20)
        outer.setSpacing(16)
        outer.addWidget(label(CHARACTERS[controller.store.character]['name'] + '와 지내는 방법', 'title'))
        tabs = QTabWidget()
        outer.addWidget(tabs)
        api, character, appearance, memory = QWidget(), QWidget(), QWidget(), QWidget()
        for page, title in ((api, '대화 연결'), (character, '캐릭터'),
                            (appearance, '화면'), (memory, '기억')):
            page.setObjectName('settingsPage')
            scroller = QScrollArea()
            scroller.setWidgetResizable(True)
            scroller.setWidget(page)
            tabs.addTab(scroller, title)
        form = QFormLayout(api)
        mcp_page = QWidget()
        mcp_layout = QVBoxLayout(mcp_page)
        mcp_layout.addWidget(label('현재 모델에 외부 도구를 연결합니다. 별도의 AI 모델이 아닙니다.', 'notice'))
        mcp_layout.addWidget(button('MCP 서버·도구 관리', self.open_mcp))
        mcp_layout.addStretch()
        tabs.addTab(mcp_page, '도구·MCP')
        form.setSpacing(14)
        self.demo = QCheckBox('데모 모드 · API 없이 조작해 보기')
        self.demo.setChecked(s['demo'])
        form.addRow(self.demo)
        self.provider = QComboBox()
        for key, title in PROVIDERS.items():
            self.provider.addItem(title, key)
        self.provider.setCurrentIndex(list(PROVIDERS).index(s['provider']))
        form.addRow('API 서비스', self.provider)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.Password)
        form.addRow('API 키', self.key)
        self.persist = QCheckBox('이 PC에 서비스별 키 암호화 저장')
        self.persist.setEnabled(sys.platform == 'win32')
        form.addRow(self.persist)
        self.remove_key = QCheckBox('이 서비스의 저장된 키 삭제')
        form.addRow(self.remove_key)
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.setInsertPolicy(QComboBox.NoInsert)
        self.model.lineEdit().setMaxLength(160)
        self.model.lineEdit().setPlaceholderText('목록에서 선택하거나 모델 ID 직접 입력')
        form.addRow('모델 · 직접 입력 가능', self.model)
        self.base = QLineEdit(s['ollama_url'])
        self.base_label = label('Ollama 서버 주소')
        form.addRow(self.base_label, self.base)
        self.refresh = button('모델 목록 가져오기', self.refresh_models)
        form.addRow(self.refresh)
        self.connection_note = label('', 'notice')
        self.connection_note.setWordWrap(True)
        form.addRow(self.connection_note)
        self.catalog = ModelCatalog(self)
        self.catalog.loaded.connect(self.models_loaded)
        self.catalog.failed.connect(self.catalog_error)
        self.finished.connect(lambda _: self.catalog.cancel())
        self.drafts = {}
        self.active_provider = None
        self.provider.currentIndexChanged.connect(self.switch_provider)
        self.switch_provider()
        form2 = QFormLayout(character)
        form2.setSpacing(14)
        self.current_character = QComboBox()
        self.default_character = QComboBox()
        for cid, info in CHARACTERS.items():
            self.current_character.addItem(info['name'], cid)
            self.default_character.addItem(info['name'], cid)
        self.current_character.setCurrentIndex(list(CHARACTERS).index(controller.store.character))
        self.default_character.setCurrentIndex(list(CHARACTERS).index(controller.store.settings['default_character']))
        form2.addRow('현재 대화 캐릭터', self.current_character)
        form2.addRow('새 대화 기본 캐릭터', self.default_character)
        self.profile_id = controller.store.character
        self.profile_drafts = {cid: dict(profile) for cid, profile in controller.store.profiles.items()}
        identity = self.identity = label(CHARACTERS[controller.store.character]['description'], 'notice')
        identity.setWordWrap(True)
        form2.addRow(identity)
        form2.addRow(button('캐릭터 이미지 폴더 열기', self.open_image_folder))
        form2.addRow(button('이미지 다시 읽기', self.reload_images))
        self.image_note = label('', 'muted')
        self.image_note.setWordWrap(True)
        form2.addRow(self.image_note)
        self.update_image_note()
        self.nickname = QLineEdit(s['nickname'])
        self.nickname.setMaxLength(40)
        form2.addRow('나를 부르는 호칭', self.nickname)
        self.persona = QPlainTextEdit(s['persona'])
        self.persona.setFixedHeight(100)
        form2.addRow('성격과 말투', self.persona)
        self.size = QSpinBox()
        self.size.setRange(160, 400)
        self.size.setSuffix(' px')
        self.size.setValue(s['size'])
        form2.addRow('캐릭터 이미지 크기', self.size)
        self.speed = QSpinBox()
        self.speed.setRange(15, 100)
        self.speed.setValue(s['speed'])
        form2.addRow('산책 속도', self.speed)
        self.current_character.currentIndexChanged.connect(self.switch_profile)
        self.roam = QCheckBox('자동으로 산책하기')
        self.roam.setChecked(s['roam'])
        form2.addRow(self.roam)
        self.click_effect = QCheckBox('클릭할 때 띠용띠용 탄성 효과')
        self.click_effect.setChecked(s['click_effect'])
        form2.addRow(self.click_effect)
        note = label('드래그로 다른 모니터에 옮길 수 있어요.\n이동은 현재 모니터의 작업 영역 안에서 이루어져요.', 'notice')
        note.setWordWrap(True)
        form2.addRow(note)
        screen = QFormLayout(appearance)
        screen.setSpacing(14)
        screen.addRow(label('창 가장자리와 모서리를 드래그해 크기를 조절하세요. 크기와 위치는 자동 저장됩니다.', 'notice'))
        self.pet_opacity = QSpinBox()
        self.pet_opacity.setRange(25, 100)
        self.pet_opacity.setSuffix(' %')
        self.pet_opacity.setValue(s['pet_opacity'])
        screen.addRow('캐릭터 투명도', self.pet_opacity)
        self.interface_opacity = QSpinBox()
        self.interface_opacity.setRange(35, 100)
        self.interface_opacity.setSuffix(' %')
        self.interface_opacity.setValue(s['interface_opacity'])
        screen.addRow('대화창·주식창 투명도', self.interface_opacity)
        self.pet_on_top = QCheckBox('캐릭터를 다른 창보다 위에 표시')
        self.pet_on_top.setChecked(s['pet_on_top'])
        screen.addRow(self.pet_on_top)
        self.chat_on_top = QCheckBox('대화창과 주식창을 다른 창보다 위에 표시')
        self.chat_on_top.setChecked(s['chat_on_top'])
        screen.addRow(self.chat_on_top)
        appearance_note = label('투명도가 너무 낮으면 캐릭터를 찾기 어려울 수 있어요.\n항상 위를 끄면 다른 창 뒤로 가려질 수 있습니다.', 'notice')
        appearance_note.setWordWrap(True)
        screen.addRow(appearance_note)
        mem = QVBoxLayout(memory)
        self.remember = QCheckBox('앱을 껐다 켜도 모든 채팅 탭과 기억 유지')
        self.remember.setChecked(s['remember'])
        mem.addWidget(self.remember)
        mem.addWidget(label('이 탭에서 꼭 기억할 메모'))
        self.memo = QPlainTextEdit(controller.store.active_chat['memo'])
        self.memo.setPlaceholderText('예: 나를 주군이라고 불러줘. 답변은 한국어로 짧게 해줘.')
        mem.addWidget(self.memo)
        memory_note = label('전체 대화는 PC에 평문으로 저장돼요. 오래된 대화는 영어로 자동 요약하고 최근 대화와 함께 전달해요. 실제 캐릭터 답변은 계속 한국어예요. 요약할 때 추가 API 요청이 발생하며, 세부 내용이 빠질 수 있어요.', 'notice')
        memory_note.setWordWrap(True)
        mem.addWidget(memory_note)
        mem.addWidget(label('이 탭의 장기 기억 · 직접 수정 가능'))
        self.summary = QPlainTextEdit(controller.store.active_chat['summary'])
        self.summary.setMaximumHeight(150)
        self.summary.setPlaceholderText('대화가 길어지면 자동으로 만들어져요. 비우면 원문에서 다시 요약해요.')
        mem.addWidget(self.summary)
        mem.addWidget(label(f"원문 {len(controller.store.history)}개 · 요약에 반영된 메시지 {controller.store.active_chat['summary_until']}개", 'muted'))
        self.clear = QCheckBox('저장할 때 현재 탭의 대화와 요약 지우기')
        mem.addWidget(self.clear)
        self.error = label('', 'notice')
        self.error.setWordWrap(True)
        self.error.hide()
        outer.addWidget(self.error)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(button('취소', self.reject))
        row.addWidget(button('저장하기', self.save, 'primary'))
        outer.addLayout(row)

    def stash_draft(self):
        if self.active_provider:
            self.drafts[self.active_provider] = dict(key=self.key.text().strip(),
                model=self.model.currentText().strip(), persist=self.persist.isChecked(), remove=self.remove_key.isChecked())

    def switch_provider(self, *_):
        self.stash_draft()
        self.catalog.cancel()
        provider = self.provider.currentData()
        self.active_provider = provider
        vault = self.c.vaults[provider]
        saved_models = self.c.store.settings['provider_models']
        default = self.c.store.settings['model'] if provider == self.c.store.settings['provider'] else PRESETS[provider][0]
        draft = self.drafts.get(provider, dict(key='', model=saved_models.get(provider, default), persist=vault.path.exists(), remove=False))
        self.key.setText(draft['key'])
        self.key.setPlaceholderText('저장된 키 유지 · 변경하려면 새 키 입력' if vault.session_key else '로컬 실행은 키 없이 사용 가능' if provider == 'ollama' else '선택한 서비스의 API 키')
        self.persist.setChecked(draft['persist'])
        self.remove_key.setChecked(draft['remove'])
        self.model.clear()
        self.model.addItems(PRESETS[provider])
        self.model.setCurrentText(draft['model'])
        self.base.setVisible(provider == 'ollama')
        self.base_label.setVisible(provider == 'ollama')
        self.refresh.setVisible(provider in ('ollama', 'vercel'))
        self.refresh.setEnabled(True)
        self.refresh.setText('설치된 모델 가져오기' if provider == 'ollama' else 'Gateway 모델 목록 새로고침')
        self.connection_note.setText(
            'Ollama를 실행하고 모델을 먼저 내려받아 주세요. 로컬 모델은 API 키가 필요 없어요. 서버 주소로 대화와 메모를 보냅니다.' if provider == 'ollama' else
            'Vercel AI Gateway 키를 입력하세요. 모델명은 제공사/모델 형식이에요. 대화와 메모는 Gateway를 거쳐 선택한 모델 서비스로 전송돼요.' if provider == 'vercel' else
            f'API 모드에서는 대화와 기억 메모를 {PROVIDERS[provider]}로 보냅니다. 구독과 API 요금은 별도일 수 있어요. 목록은 2026-09-14 공식 카탈로그 기준이며 사용 권한은 계정마다 달라요.')

    def refresh_models(self):
        provider = self.provider.currentData()
        if provider not in ('ollama', 'vercel'):
            return
        key = '' if self.remove_key.isChecked() else self.key.text().strip() or self.c.vaults[provider].session_key
        self.refresh.setEnabled(False)
        self.refresh.setText('가져오는 중…')
        self.catalog.fetch(provider, self.base.text(), key)

    def models_loaded(self, names):
        current = self.model.currentText()
        self.model.clear()
        self.model.addItems(names or PRESETS[self.active_provider])
        self.model.setCurrentText(current)
        self.refresh.setEnabled(True)
        self.refresh.setText(f'{len(names)}개 모델 · 다시 가져오기')
        if not names:
            self.connection_note.setText('설치된 모델이 없어요. Ollama에서 모델을 먼저 내려받아 주세요.')

    def catalog_error(self, text):
        self.refresh.setEnabled(True)
        self.refresh.setText('다시 가져오기')
        self.connection_note.setText(text)

    def open_image_folder(self):
        folder = self.c.store.character_folder(self.current_character.currentData())
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))):
            self.image_note.setText(str(folder))

    def open_mcp(self):
        from mcp_ui import McpDialog
        McpDialog(self.c, self).exec()

    def capture_profile(self):
        self.profile_drafts[self.profile_id].update(
            nickname=self.nickname.text().strip() or CHARACTERS[self.profile_id]['nickname'],
            persona=self.persona.toPlainText()[:1500], size=self.size.value(), speed=self.speed.value())

    def switch_profile(self):
        self.capture_profile()
        self.profile_id = self.current_character.currentData()
        profile = self.profile_drafts[self.profile_id]
        self.nickname.setText(profile['nickname'])
        self.persona.setPlainText(profile['persona'])
        self.size.setValue(profile['size'])
        self.speed.setValue(profile['speed'])
        self.identity.setText(CHARACTERS[self.profile_id]['description'])
        self.update_image_note()

    def update_image_note(self):
        store = self.c.store
        count = sum(store.image_path(e, fallback=False) is not None for e in EMOTIONS)
        cid = self.current_character.currentData()
        count = sum(bool(store.image_path(emotion, cid, fallback=False)) for emotion in EMOTIONS)
        prefix = CHARACTERS[cid]['prefix']
        self.image_note.setText(f'{count}/{len(EMOTIONS)}개 표정 인식 · {prefix}.cozy.webp 등\n없는 표정은 같은 캐릭터의 기본 이미지로 표시해요.')

    def reload_images(self):
        self.c.pet.reload_size()
        self.c.chat.refresh_status()
        self.update_image_note()

    def save(self):
        c = self.c
        self.stash_draft()
        provider = self.provider.currentData()
        model = self.model.currentText().strip()
        if not model or any(ch.isspace() for ch in model):
            self.error.setText('공백 없이 모델 ID를 입력해 주세요.')
            self.error.show(); return
        key = '' if self.remove_key.isChecked() else (self.key.text().strip() or c.vaults[provider].session_key)
        if not self.demo.isChecked() and provider != 'ollama' and not key:
            self.error.setText('API 키를 입력하거나 데모 모드를 켜 주세요.')
            self.error.show(); return
        try:
            base = ollama_base(self.base.text())
            for pid, draft in self.drafts.items():
                k = '' if draft['remove'] else draft['key'] or c.vaults[pid].session_key
                if any(ord(ch) < 33 or ord(ch) > 126 for ch in k):
                    raise ValueError('API 키에 공백이나 잘못된 문자가 있어요.')
            for pid, draft in self.drafts.items():
                k = '' if draft['remove'] else draft['key'] or c.vaults[pid].session_key
                c.vaults[pid].set(k, draft['persist'])
        except (ValueError, OSError) as e:
            self.error.setText(str(e) if isinstance(e, ValueError) else '키를 저장하지 못했어요. 암호화 저장을 끄고 다시 시도해 주세요.')
            self.error.show(); return
        s = c.store.settings
        was_demo = s['demo']
        s['provider_models'].update({pid: draft['model'] for pid, draft in self.drafts.items() if draft['model']})
        s.update(provider=provider, ollama_url=base, click_effect=self.click_effect.isChecked(),
                 demo=self.demo.isChecked(), model=model, roam=self.roam.isChecked(),
                 remember=self.remember.isChecked(),
                 default_character=self.default_character.currentData(),
                 pet_opacity=self.pet_opacity.value(),
                 interface_opacity=self.interface_opacity.value(),
                 pet_on_top=self.pet_on_top.isChecked(), chat_on_top=self.chat_on_top.isChecked())
        self.capture_profile()
        c.store.profiles.update(self.profile_drafts)
        chat = c.store.active_chat
        chat['character'] = self.current_character.currentData()
        chat['memo'] = self.memo.toPlainText()[:4000]
        chat['summary'] = self.summary.toPlainText()[:6000].strip()
        if not chat['summary']:
            chat['summary_until'] = 0
        if self.clear.isChecked():
            c.store.clear_history()
        if was_demo != s['demo']:
            # Keep demo and live records available, but do not mix their context.
            c.store.new_chat()
            c.store.active_chat['title'] = '데모 대화' if s['demo'] else 'API 대화'
        c.chat.reload_chat()
        c.persist()
        c.apply_appearance()
        self.accept()


class DragHeader(QFrame):
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.offset = e.globalPosition().toPoint() - self.window().pos()
    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton and hasattr(self, 'offset'):
            self.window().move(e.globalPosition().toPoint() - self.offset)
    def mouseReleaseEvent(self, e):
        if hasattr(self, 'offset'):
            del self.offset


class ChatWindow(QWidget):
    def __init__(self, controller):
        super().__init__(None, Qt.Tool | Qt.WindowStaysOnTopHint)
        self.c = controller
        self.setObjectName('chat')
        self.setWindowTitle('이즈나 비서')
        self.resize(420, 570)
        self.setMinimumSize(360, 420)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(5)
        header = DragHeader()
        header.setObjectName('header')
        row = QHBoxLayout(header)
        row.setContentsMargins(4, 2, 4, 2)
        avatar = self.avatar = QLabel()
        avatar.setPixmap(QPixmap(str(ASSETS / 'Izuna.cozy.webp')).scaled(48, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        avatar.setAttribute(Qt.WA_TransparentForMouseEvents)
        avatar.hide()
        titles = QVBoxLayout()
        self.character_title = label('이즈나')
        self.character_subtitle = label('', 'muted')
        titles.addWidget(self.character_title)
        self.character_subtitle.hide()
        row.addLayout(titles)
        row.addStretch()
        self.list_button = button('대화 목록', self.show_conversations, 'close')
        row.addWidget(self.list_button)
        self.new_button = button('새 대화', self.new_tab, 'close')
        row.addWidget(self.new_button)
        row.addWidget(button('설정', self.c.open_settings, 'close'))
        row.addWidget(button('⋯', self.show_more, 'close'))
        close = button('×', self.hide, 'close')
        close.setToolTip('대화창 닫기 · 이즈나는 계속 머물러요')
        row.addWidget(close)
        outer.addWidget(header)
        statusrow = QHBoxLayout()
        self.badge = label('', 'badge')
        statusrow.addWidget(self.badge)
        statusrow.addStretch()
        outer.addLayout(statusrow)
        self.folder_indicator = button('폴더 작업 종료', self.c.clear_folder, 'close')
        self.folder_indicator.hide()
        outer.addWidget(self.folder_indicator)
        tabrow = QHBoxLayout()
        self.tabs = QTabBar(self)
        self.tabs.hide()  # Index adapter for existing conversation operations; no horizontal tabs.
        self.tabs.setExpanding(False)
        self.tabs.setDrawBase(False)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tabs.customContextMenuRequested.connect(self.tab_menu)
        self.tabs.currentChanged.connect(self.switch_tab)
        self.tabs.tabBarDoubleClicked.connect(self.rename_tab)
        self.new_button.setToolTip('빈 채팅 탭 만들기')
        characterrow = QHBoxLayout()
        self.character_select = QComboBox(self)
        self.character_select.hide()
        for cid, info in CHARACTERS.items():
            self.character_select.addItem(info['name'] + ' 모드', cid)
        self.character_select.currentIndexChanged.connect(self.change_character)
        characterrow.addStretch()
        self.more = button('이전 대화 ↑', self.show_earlier, 'close')
        self.more.setParent(self)
        self.more.hide()
        self.visible_count = 60
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.messages = QWidget()
        self.messages.setObjectName('messageList')
        self.messages.setStyleSheet('QWidget#messageList { background: transparent; }')
        self.msglayout = QVBoxLayout(self.messages)
        self.msglayout.setContentsMargins(0, 0, 3, 0)
        self.msglayout.setSpacing(12)
        self.msglayout.addStretch()
        self.scroll.setWidget(self.messages)
        self.scroll_timer = QTimer(self)
        self.scroll_timer.setSingleShot(True)
        self.scroll_timer.timeout.connect(lambda: self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum()))
        outer.addWidget(self.scroll, 1)
        self.status = label('대화할 준비가 됐어요.', 'muted')
        self.status.setWordWrap(True)
        outer.addWidget(self.status)
        inputrow = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setMaxLength(4000)
        self.input.setPlaceholderText('이즈나에게 말 걸기…')
        self.input.returnPressed.connect(self.submit)
        inputrow.addWidget(self.input, 1)
        self.sendbutton = button('보내기', self.submit, 'primary')
        inputrow.addWidget(self.sendbutton)
        outer.addLayout(inputrow)
        self.reload_chat()
        self.geometry_timer = QTimer(self)
        self.geometry_timer.setSingleShot(True)
        self.geometry_timer.timeout.connect(self.save_geometry)

    def save_geometry(self, force=False):
        if (self.isVisible() or force) and not self.isMinimized():
            rect = self.normalGeometry() if self.isMaximized() else self.geometry()
            self.c.store.settings['window_geometry'] = dict(x=rect.x(), y=rect.y(), width=rect.width(), height=rect.height())
            self.c.persist()

    def moveEvent(self, event):
        super().moveEvent(event)
        if hasattr(self, 'geometry_timer'):
            self.geometry_timer.start(350)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'geometry_timer'):
            self.geometry_timer.start(350)

    def hideEvent(self, event):
        self.save_geometry(force=True)
        self.save_draft()
        self.c.persist()
        super().hideEvent(event)

    def show_more(self):
        menu = QMenu(self)
        menu.addAction('폴더 작업 시작…', self.c.choose_folder)
        menu.addAction('폴더 작업 종료', self.c.clear_folder)
        menu.addAction('주식 · 포트폴리오', self.c.open_stocks)
        action = menu.addAction('이전 대화 더 보기', self.show_earlier)
        action.setEnabled(len(self.c.store.history) > self.visible_count)
        menu.exec(QCursor.pos())

    def show_conversations(self):
        if self.c.busy:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('대화 목록')
        dialog.resize(420, 480)
        layout = QVBoxLayout(dialog)
        search = QLineEdit()
        search.setPlaceholderText('대화 제목 검색')
        listing = QListWidget()
        layout.addWidget(search)
        layout.addWidget(listing)
        def refresh():
            listing.clear()
            for chat in self.c.store.chats:
                if search.text().casefold() not in chat['title'].casefold():
                    continue
                timestamp = chat.get('updated_at', '')
                try:
                    timestamp = datetime.fromisoformat(timestamp).astimezone().strftime('%Y-%m-%d %H:%M')
                except ValueError:
                    timestamp = '수정시간 기록 없음'
                item = QListWidgetItem(f"{chat['title']}\n{CHARACTERS[chat['character']]['name']} · {timestamp}")
                item.setData(Qt.UserRole, chat['id'])
                listing.addItem(item)
                if chat['id'] == self.c.store.active_id:
                    listing.setCurrentItem(item)
        def select(item):
            index = next(i for i, chat in enumerate(self.c.store.chats) if chat['id'] == item.data(Qt.UserRole))
            self.switch_tab(index)
            dialog.accept()
        def context(pos):
            item = listing.itemAt(pos)
            if not item:
                return
            ident = item.data(Qt.UserRole)
            menu = QMenu(dialog)
            rename = menu.addAction('이름 변경')
            duplicate = menu.addAction('복제')
            delete = menu.addAction('삭제')
            choice = menu.exec(listing.mapToGlobal(pos))
            self.save_draft()
            chat = next(c for c in self.c.store.chats if c['id'] == ident)
            if choice == rename:
                title, ok = QInputDialog.getText(dialog, '이름 변경', '새 이름', text=chat['title'])
                if ok and title.strip():
                    chat['title'] = title.strip()[:60]
                    chat['updated_at'] = datetime.now().astimezone().isoformat()
            elif choice == duplicate:
                self.save_draft()
                selected = self.c.store.active_id
                self.c.store.select_chat(ident)
                self.c.store.new_chat(duplicate=True)
                self.c.store.select_chat(selected)
            elif choice == delete:
                if QMessageBox.question(dialog, '삭제', '이 대화와 기억을 삭제할까요?') == QMessageBox.Yes:
                    self.save_draft()
                    self.c.store.delete_chat(ident)
            self.reload_chat()
            self.c.pet.reload_size()
            self.c.persist()
            refresh()
        search.textChanged.connect(refresh)
        listing.itemActivated.connect(select)
        listing.itemClicked.connect(select)
        listing.setContextMenuPolicy(Qt.CustomContextMenu)
        listing.customContextMenuRequested.connect(context)
        refresh()
        dialog.exec()

    def reload_chat(self):
        self.tabs.blockSignals(True)
        while self.tabs.count():
            self.tabs.removeTab(0)
        for chat in self.c.store.chats:
            index = self.tabs.addTab(chat['title'])
            self.tabs.setTabData(index, chat['id'])
            self.tabs.setTabToolTip(index, chat['title'] + ' · ' + CHARACTERS[chat['character']]['name'] + '\n우클릭: 이름 변경 / 복제 / 삭제')
            if chat['id'] == self.c.store.active_id:
                self.tabs.setCurrentIndex(index)
        self.tabs.blockSignals(False)
        self.character_select.blockSignals(True)
        self.character_select.setCurrentIndex(list(CHARACTERS).index(self.c.store.character))
        self.character_select.blockSignals(False)
        self.input.setText(self.c.store.active_chat['draft'])
        self.visible_count = 60
        self.refresh_status()
        self.reset_messages()

    def save_draft(self):
        if self.c.store.active_chat['draft'] != self.input.text():
            self.c.store.active_chat['updated_at'] = datetime.now().astimezone().isoformat()
        self.c.store.active_chat['draft'] = self.input.text()

    def switch_tab(self, index):
        if self.c.busy or index < 0:
            return
        self.save_draft()
        self.c.store.select_chat(self.tabs.tabData(index))
        self.reload_chat()
        self.c.pet.reload_size()
        self.c.persist()

    def new_tab(self, checked=False, duplicate=False):
        if self.c.busy:
            return
        self.save_draft()
        self.c.store.new_chat(duplicate=duplicate)
        self.reload_chat()
        self.c.persist()

    def rename_tab(self, index):
        if self.c.busy or index < 0:
            return
        chat = next(c for c in self.c.store.chats if c['id'] == self.tabs.tabData(index))
        title, ok = QInputDialog.getText(self, '탭 이름 변경', '새 이름', text=chat['title'])
        if ok and title.strip():
            self.save_draft()
            chat['title'] = title.strip()[:60]
            self.reload_chat()
            self.c.persist()

    def tab_menu(self, pos):
        index = self.tabs.tabAt(pos)
        if self.c.busy or index < 0:
            return
        self.tabs.setCurrentIndex(index)
        menu = QMenu(self)
        menu.addAction('이름 변경', lambda: self.rename_tab(index))
        menu.addAction('대화 복제', lambda: self.new_tab(duplicate=True))
        menu.addAction('대화 삭제', self.delete_tab)
        menu.exec(self.tabs.mapToGlobal(pos))

    def delete_tab(self):
        if self.c.busy:
            return
        if QMessageBox.question(self, '대화 삭제', '현재 탭의 대화와 기억을 삭제할까요?') != QMessageBox.Yes:
            return
        self.c.store.delete_chat(self.c.store.active_id)
        self.reload_chat()
        self.c.pet.reload_size()
        self.c.persist()

    def change_character(self, index):
        if self.c.busy or index < 0:
            return
        self.save_draft()
        self.c.store.active_chat['character'] = self.character_select.currentData()
        self.reload_chat()
        self.c.pet.reload_size()
        self.c.pet.expression('cozy')
        self.c.persist()

    def show_earlier(self):
        self.visible_count += 60
        self.reset_messages()
        self.scroll_timer.stop()
        self.scroll.verticalScrollBar().setValue(0)

    def refresh_status(self):
        self.badge.setText('● DEMO · 미연결' if self.c.store.settings['demo'] else '● ' + self.c.store.settings['provider'].capitalize())
        self.badge.setToolTip(self.c.store.settings['model'])
        info = CHARACTERS[self.c.store.character]
        self.character_title.setText(self.c.store.active_chat['title'][:16])
        self.character_title.setToolTip(self.c.store.active_chat['title'])
        self.badge.setText(info['name'] + ' · ' + ('데모' if self.c.store.settings['demo'] else self.c.store.settings['provider'] + ' · ' + self.c.store.settings['model']))
        self.character_subtitle.setText(self.c.store.effective_settings['nickname'] + ' 곁의 작은 비서')
        self.input.setPlaceholderText(info['name'] + '에게 말 걸기…')
        self.setWindowTitle(info['name'] + ' 비서')
        path = self.c.store.image_path('cozy')
        pix = QPixmap(str(path)) if path else QPixmap()
        self.avatar.setPixmap(pix.scaled(48, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation) if not pix.isNull() else pix)
        self.avatar.hide()

    def reset_messages(self):
        while self.msglayout.count() > 1:
            item = self.msglayout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        if not self.c.store.history:
            self.add_message('assistant', self.c.store.effective_settings['nickname'] + ', ' + CHARACTERS[self.c.store.character]['name'] + '예요. 오늘은 무엇을 도와드릴까요?')
        for m in self.c.store.history[-self.visible_count:]:
            self.add_message(m['role'], m['content'], m.get('character', 'izuna'))
        self.more.setEnabled(len(self.c.store.history) > self.visible_count)

    def add_message(self, role, text, character=None):
        group = QWidget()
        group_layout = QVBoxLayout(group)
        group_layout.setContentsMargins(0, 0, 0, 0)
        group_layout.setSpacing(4)
        is_user = role == 'user'
        name = label(self.c.store.effective_settings['nickname'] if is_user else CHARACTERS[character or self.c.store.character]['name'], 'muted')
        name.setAlignment(Qt.AlignRight if is_user else Qt.AlignLeft)
        group_layout.addWidget(name)
        bubble = label(text, 'userBubble' if is_user else 'assistantBubble')
        bubble.setWordWrap(True)
        bubble.setTextInteractionFlags(Qt.TextSelectableByMouse)
        group_layout.addWidget(bubble)
        group_layout.setContentsMargins(28 if is_user else 0, 0, 0 if is_user else 28, 0)
        self.msglayout.insertWidget(self.msglayout.count() - 1, group)
        self.scroll_timer.start(30)

    def set_busy(self, busy):
        self.sendbutton.setText('중지' if busy else '보내기')
        self.tabs.setEnabled(not busy)
        self.list_button.setEnabled(not busy)
        self.new_button.setEnabled(not busy)
        self.character_select.setEnabled(not busy)
        self.status.setText(CHARACTERS[self.c.store.character]['name'] + '가 생각하고 있어요…' if busy else '대화할 준비가 됐어요.')

    def submit(self):
        if self.c.busy:
            self.c.cancel()
            return
        text = self.input.text().strip()
        if text and self.c.send(text):
            self.input.clear()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(e)

    def closeEvent(self, e):
        self.hide()
        e.ignore()


class PortfolioPages(QStackedWidget):
    def minimumSizeHint(self): return QSize(200, 160)
    def sizeHint(self): return QSize(700, 340)
    def addTab(self, widget, title):
        widget.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        return self.addWidget(widget)


class StockWindow(QWidget):
    """Read-only quotes plus a locally stored manual portfolio."""
    def __init__(self, controller):
        super().__init__(None, Qt.Tool)
        self.c = controller
        self.setObjectName('stocks')
        self.setWindowTitle('주식 · 나의 포트폴리오')
        self.resize(850, 560)
        self.setMinimumSize(680, 440)
        self.quotes = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)
        header = QHBoxLayout()
        header.addWidget(label('내 자산', 'title'))
        self.view_picker = QComboBox()
        self.view_picker.addItems(['보유종목', '도넛 그래프', '월별 성과', '관심종목', '매매 기록'])
        header.addWidget(self.view_picker)
        header.addStretch()
        self.refresh_button = button('시세 새로고침', self.refresh)
        header.addWidget(self.refresh_button)
        outer.addLayout(header)
        note = label('종목을 더블클릭하면 차트가 열려요. 시세는 지연될 수 있어요.', 'muted')
        note.setWordWrap(True)
        outer.addWidget(note)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(['종목', '현재가', '일간', '수량', '평가액', '손익', '수익률'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.cellDoubleClicked.connect(lambda row, col: self.open_chart(row))
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.chart_menu)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setMinimumHeight(160)
        self.table.setWordWrap(False)
        self.table.horizontalHeader().setMinimumSectionSize(70)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for column in range(1, 7):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeToContents)
        for column in (2,5,6): self.table.setColumnHidden(column,True)
        from portfolio_views import AllocationView
        self.views = PortfolioPages()
        self.view_picker.currentIndexChanged.connect(self.views.setCurrentIndex)
        self.views.addTab(self.table, '보유종목')
        self.allocation = AllocationView(self)
        self.views.addTab(self.allocation, '도넛 그래프')
        from investment_tools import RecordView
        for key, title in [('months', '월별 성과'), ('watchlist', '관심종목'), ('trades', '매매 기록')]:
            self.views.addTab(RecordView(self, key), title)
        self.views.currentChanged.connect(lambda _: self.allocation.refresh())
        outer.addWidget(self.views, 1)
        totals = QHBoxLayout()
        self.krw_total = label('원화 평가액 —', 'badge')
        self.usd_total = label('달러 평가액 —', 'badge')
        self.updated = label('아직 시세를 불러오지 않았어요.', 'muted')
        totals.addWidget(self.krw_total)
        totals.addWidget(self.usd_total)
        totals.addStretch()
        totals.addWidget(self.updated)
        outer.addLayout(totals)
        self.position_dialog = QDialog(self)
        self.editing_position = None
        self.position_dialog.setWindowTitle('자산 추가 / 수정')
        self.position_dialog.resize(420, 490)
        entry = QFormLayout(self.position_dialog)
        self.market = QComboBox()
        self.market.addItem('미국', 'US')
        self.market.addItem('국내 KRX', 'KRX')
        self.market.addItem('국내 KOSDAQ', 'KOSDAQ')
        self.symbol = QLineEdit()
        self.symbol.setPlaceholderText('AAPL 또는 005930')
        self.symbol.setMaxLength(30)
        self.stock_name = QLineEdit()
        self.stock_name.setPlaceholderText('표시 이름 · 선택')
        self.stock_name.setMaxLength(40)
        self.quantity = QDoubleSpinBox()
        self.quantity.setRange(0, 1_000_000_000)
        self.quantity.setDecimals(6)
        self.quantity.setPrefix('수량 ')
        self.average = QDoubleSpinBox()
        self.average.setRange(0, 1_000_000_000_000)
        self.average.setDecimals(4)
        self.average.setPrefix('평단 ')
        for title, widget in [('시장', self.market), ('종목 코드', self.symbol), ('이름', self.stock_name), ('수량 / 현금 금액', self.quantity), ('평균 매입가', self.average)]:
            entry.addRow(title, widget)
        self.account = QLineEdit('기본 계좌'); self.account.setPlaceholderText('계좌 이름'); self.account.setMaxLength(60)
        self.sector = QLineEdit('미분류'); self.sector.setPlaceholderText('섹터'); self.sector.setMaxLength(60)
        self.cash_position = QCheckBox('현금 (수량에 금액 입력)')
        entry.addRow('계좌 이름', self.account); entry.addRow('섹터', self.sector); entry.addRow(self.cash_position)
        entry.addRow(button('저장', self.add_position, 'primary'))
        entry.addRow(button('닫기', self.position_dialog.reject))
        self.cash_position.toggled.connect(lambda checked: self.symbol.setEnabled(not checked))
        self.cash_position.toggled.connect(lambda checked: self.average.setEnabled(not checked))
        actions=QHBoxLayout()
        actions.addWidget(button('+ 자산 추가', self.new_position, 'primary'))
        actions.addWidget(button('선택 수정', self.show_position_editor))
        actions.addWidget(button('선택 삭제', self.remove_position))
        self.show_profit = QCheckBox('손익 자세히')
        self.show_profit.toggled.connect(lambda visible: [self.table.setColumnHidden(column,not visible) for column in (2,5,6)])
        actions.addWidget(self.show_profit)
        actions.addStretch()
        self.asset_actions=QWidget(); self.asset_actions.setLayout(actions); outer.addWidget(self.asset_actions)
        self.views.currentChanged.connect(lambda index: self.asset_actions.setVisible(index==0))
        self.market_client = MarketClient(self)
        self.market_client.quoteLoaded.connect(self.quote_loaded)
        self.market_client.failed.connect(self.quote_failed)
        self.market_client.completed.connect(self.refresh_finished)
        self.auto_timer = QTimer(self)
        self.auto_timer.timeout.connect(self.refresh)
        self.auto_timer.start(30000)
        self.render()

    def new_position(self):
        self.editing_position = None
        self.symbol.clear(); self.stock_name.clear(); self.quantity.setValue(0); self.average.setValue(0)
        self.cash_position.setChecked(False)
        self.position_dialog.exec()

    def show_position_editor(self):
        if self.table.currentRow()<0: return
        self.edit_position(); self.position_dialog.exec()

    def edit_position(self):
        row = self.table.currentRow()
        if not 0 <= row < len(self.c.store.portfolio): return
        self.editing_position = row
        item = self.c.store.portfolio[row]
        self.market.setCurrentIndex(self.market.findData(item['market']))
        self.symbol.setText(item['symbol']); self.stock_name.setText(item['name'])
        self.quantity.setValue(item['quantity']); self.average.setValue(item['average'])
        self.account.setText(item.get('account', '기본 계좌')); self.sector.setText(item.get('sector', '미분류'))
        self.cash_position.setChecked(item.get('cash', False))

    def add_position(self):
        from stocks import provider_symbol
        symbol = self.symbol.text().strip().upper()
        market = self.market.currentData()
        cash = self.cash_position.isChecked()
        if cash: symbol = 'CASH-USD' if market == 'US' else 'CASH-KRW'
        try:
            if not cash: provider_symbol(symbol, market)
        except ValueError as exc:
            QMessageBox.information(self, '종목 코드 확인', str(exc))
            return
        value = dict(symbol=symbol, market=market, name=self.stock_name.text().strip(),
                     quantity=self.quantity.value(), average=1 if cash else self.average.value(),
                     account=self.account.text().strip() or '기본 계좌', sector=self.sector.text().strip() or '미분류',
                     currency='USD' if market == 'US' else 'KRW', cash=cash)
        existing = next((i for i, p in enumerate(self.c.store.portfolio)
                         if p['symbol'] == symbol and p['market'] == market and p.get('account', '기본 계좌') == value['account']), None)
        if self.editing_position is not None:
            if existing is not None and existing != self.editing_position:
                QMessageBox.information(self, '중복 자산', '같은 계좌에 이미 있는 종목입니다. 해당 자산을 선택해 수정하세요.')
                return
            existing = self.editing_position
        previous = list(self.c.store.portfolio)
        self.market_client.cancel(emit=False)
        self.quotes = {}
        if existing is None:
            if len(self.c.store.portfolio) >= 100:
                QMessageBox.information(self, '포트폴리오', '종목은 최대 100개까지 저장할 수 있어요.')
                return
            self.c.store.portfolio.append(value)
        else:
            self.c.store.portfolio[existing] = value
        try: self.c.store.save()
        except OSError:
            self.c.store.portfolio = previous
            QMessageBox.warning(self.position_dialog, '저장 실패', '장부를 저장하지 못했습니다. 저장 공간과 권한을 확인하세요.')
            return
        self.editing_position = None
        self.position_dialog.accept()
        self.render()
        self.refresh()

    def open_chart(self, row):
        if not 0 <= row < len(self.c.store.portfolio): return
        from charts import ChartWindow
        from stocks import provider_symbol
        item = self.c.store.portfolio[row]
        if item.get('cash'): return
        dialog = ChartWindow(provider_symbol(item['symbol'], item['market']), self)
        dialog.canvas.trades = [t for t in self.c.store.investments['trades'] if t['symbol'] == item['symbol'] and t['market'] == item['market'] and t['account'] == item.get('account', '기본 계좌')]
        dialog.exec()

    def chart_menu(self, pos):
        row = self.table.rowAt(pos.y())
        if row < 0: return
        from stocks import provider_symbol
        from urllib.parse import quote
        item = self.c.store.portfolio[row]
        if item.get('cash'): return
        symbol = provider_symbol(item['symbol'], item['market'])
        menu = QMenu(self)
        menu.addAction('내부 차트', lambda: self.open_chart(row))
        tv = ('KRX:' + item['symbol']) if item['market'] in ('KRX', 'KOSDAQ') else item['symbol']
        menu.addAction('TradingView', lambda: QDesktopServices.openUrl(QUrl('https://www.tradingview.com/chart/?symbol=' + quote(tv, safe=''))))
        menu.addAction('Yahoo Finance', lambda: QDesktopServices.openUrl(QUrl('https://finance.yahoo.com/quote/' + quote(symbol, safe=''))))
        menu.exec(self.table.mapToGlobal(pos))

    def remove_position(self):
        row = self.table.currentRow()
        if not 0 <= row < len(self.c.store.portfolio):
            return
        self.market_client.cancel(emit=False)
        del self.c.store.portfolio[row]
        self.quotes = {}
        self.c.persist()
        self.render()

    def refresh(self):
        if self.market_client.replies:
            return
        self.refresh_button.setEnabled(False)
        self.refresh_button.setText('불러오는 중…')
        self.updated.setText('시세 확인 중…')
        self.market_client.fetch(list(self.c.store.portfolio))

    def quote_loaded(self, index, quote):
        self.quotes[index] = quote
        self.render()

    def quote_failed(self, index, message):
        self.quotes[index] = dict(error=message)
        self.render()

    def refresh_finished(self):
        self.refresh_button.setEnabled(True)
        self.refresh_button.setText('시세 새로고침')
        self.updated.setText('앱 수신 ' + datetime.now().strftime('%H:%M:%S') + ' · 시세 자체는 지연될 수 있어요')

    @staticmethod
    def number(value, currency):
        if currency == 'KRW':
            return f'{value:,.0f}원'
        return f'${value:,.2f}' if currency == 'USD' else f'{value:,.2f} {currency}'.strip()

    def render(self):
        self.table.setRowCount(len(self.c.store.portfolio))
        totals = {'KRW': 0.0, 'USD': 0.0}
        for row, position in enumerate(self.c.store.portfolio):
            quote = self.quotes.get(row, {})
            if position.get('cash'):
                quote = dict(price=1, percent=None, currency=position.get('currency', 'KRW'))
            market = '미국' if position['market'] == 'US' else position['market']
            title = position['name'] or position['symbol']
            if position.get('account', '기본 계좌') != '기본 계좌': title += ' · ' + position['account']
            values = [f'{title} · {market}/{position["symbol"]}', '—', '—', f'{position["quantity"]:,.6f}'.rstrip('0').rstrip('.'), '—', '—', '—']
            if quote.get('error'):
                values[1] = '오류'
                values[2] = quote['error']
            elif 'price' in quote:
                currency = quote.get('currency') or ('USD' if position['market'] == 'US' else 'KRW')
                value, profit, profit_percent = position_values(position, quote)
                values[1] = self.number(quote['price'], currency)
                values[2] = '—' if quote['percent'] is None else f'{quote["percent"]:+.2f}%'
                values[4] = self.number(value, currency)
                values[5] = ('+' if profit > 0 else '') + self.number(profit, currency)
                values[6] = '—' if profit_percent is None else f'{profit_percent:+.2f}%'
                if currency in totals:
                    totals[currency] += value
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if column > 0:
                    cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if value.startswith('+'):
                    cell.setForeground(QColor('#ff707d'))
                elif value.startswith('-'):
                    cell.setForeground(QColor('#73a7ff'))
                self.table.setItem(row, column, cell)
        self.krw_total.setText('원화 평가액 ' + self.number(totals['KRW'], 'KRW'))
        self.usd_total.setText('달러 평가액 ' + self.number(totals['USD'], 'USD'))
        self.allocation.refresh()

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()

    def closeEvent(self, event):
        self.hide()
        event.ignore()


class PetWindow(QWidget):
    def __init__(self, controller):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.c = controller
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowTitle('이즈나')
        self.setCursor(Qt.OpenHandCursor)
        self.setMouseTracking(True)
        self.emotion = 'cozy'
        self.pressed = False
        self.dragged = False
        self.hovered = False
        self.settings_open = False
        self.direction = 1
        self.walking = False
        self.phase = 0.0
        self.bounce_start = -100.0
        self.last_interaction = time.monotonic()
        self.moving_now = False
        self.next_action = time.monotonic() + 4
        self.emotion_until = 0
        self.last_tick = time.monotonic()
        self.base_y = 0
        self.float_x = 0.0
        self.cache = {}
        self.last_visual = None
        self.reload_size()
        area = QApplication.primaryScreen().availableGeometry()
        self.move(area.right() - self.width() - 80, area.bottom() - self.height() + 1)
        self.base_y = self.y()
        self.float_x = float(self.x())
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(33)
        for screen in QApplication.screens():
            screen.availableGeometryChanged.connect(self.ensure_visible)
        QApplication.instance().screenRemoved.connect(self.ensure_visible)

    def area(self):
        screen = QApplication.screenAt(self.frameGeometry().center()) or QApplication.primaryScreen()
        return screen.availableGeometry()

    def reload_size(self):
        bottom = self.y() + self.height()
        height = self.c.store.effective_settings['size']
        self.setFixedSize(round(height * 701 / 1024) + 80, height + 96)
        self.cache.clear()
        self.last_visual = None
        self.move(self.x(), bottom - self.height())
        self.base_y = self.y()
        self.ensure_visible()
        self.update_visual(0)

    def ensure_visible(self, *_):
        self.move(clamp_position(self.pos(), self.size(), self.area()))
        self.base_y = self.y()
        self.float_x = float(self.x())

    def expression(self, emotion, seconds=7):
        self.emotion = emotion if emotion in EMOTIONS else 'cozy'
        self.emotion_until = time.monotonic() + seconds
        self.update_visual(0)

    def frame(self, emotion, flip):
        key = (emotion, flip)
        if key not in self.cache:
            path = self.c.store.image_path(emotion)
            pix = QPixmap(str(path)) if path else QPixmap()
            if pix.isNull():
                pix = QPixmap(210, 230)
                pix.fill(Qt.transparent)
                painter = QPainter(pix)
                painter.setRenderHint(QPainter.Antialiasing)
                painter.setBrush(QColor('#253d50'))
                painter.setPen(QColor('#91dce8'))
                painter.drawRoundedRect(4, 4, 202, 222, 24, 24)
                painter.setFont(QFont('Malgun Gothic', 13))
                painter.drawText(pix.rect(), Qt.AlignCenter, CHARACTERS[self.c.store.character]['name'] + '\n이미지 추가\n\n설정 → 이미지 폴더')
                painter.end()
            height = self.c.store.effective_settings['size']
            pix = pix.scaled(round(height * 701 / 1024), height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            if flip:
                pix = QPixmap.fromImage(pix.toImage().mirrored(True, False))
            self.cache[key] = (pix, QRegion(pix.mask()))
        return self.cache[key]

    def bounce_parameters(self, elapsed):
        if not self.c.store.settings['click_effect']:
            return 1.0, 1.0, 0.0, 0.0
        if self.pressed and not self.dragged:
            return 1.02, .98, 0.0, 0.0
        if not 0 <= elapsed <= 1.25:
            return 1.0, 1.0, 0.0, 0.0
        wave = math.sin(22 * elapsed) * math.exp(-4.5 * elapsed)
        return 1 - .09 * wave, 1 + .14 * wave, 5 * wave, 28 * abs(math.sin(12 * elapsed)) * math.exp(-3.2 * elapsed)

    def update_visual(self, bob):
        mood = self.emotion
        if self.moving_now:
            mood = 'walking to left' if self.direction < 0 else 'walking to right'
        sx, sy, angle, jump = self.bounce_parameters(time.monotonic() - self.bounce_start)
        visual = (mood, bob, round(sx, 3), round(sy, 3), round(angle, 2), round(jump))
        if visual == self.last_visual:
            return
        self.last_visual = visual
        pix, _ = self.frame(mood, False)
        if abs(sx-1) > .001 or abs(sy-1) > .001 or abs(angle) > .01:
            transform = QTransform().rotate(angle).scale(sx, sy)
            pix = pix.transformed(transform, Qt.SmoothTransformation)
        self.pix = pix
        self.draw_x = (self.width() - pix.width()) // 2
        self.draw_y = self.height() - 8 - pix.height() - bob - round(jump)
        self.setMask(QRegion(pix.mask()).translated(self.draw_x, self.draw_y))
        self.update()

    def paintEvent(self, e):
        if hasattr(self, 'pix'):
            painter = QPainter(self)
            painter.drawPixmap(self.draw_x, self.draw_y, self.pix)

    def tick(self):
        now = time.monotonic()
        dt = min(now - self.last_tick, 0.1)
        self.last_tick = now
        if not self.isVisible():
            return
        stopped = self.pressed or self.hovered or self.settings_open or self.c.chat.isVisible() or self.c.busy
        if now > self.emotion_until and not stopped:
            self.emotion = 'sleeping' if not self.c.store.settings['roam'] and now - self.last_interaction > 60 else 'cozy' if self.walking else 'sleepy' if int(now) % 35 > 28 else 'smiling'
        if now > self.next_action and not stopped:
            self.walking = not self.walking
            if self.walking:
                self.direction = random.choice((-1, 1))
            self.next_action = now + random.uniform(3, 7)
        move = self.c.store.settings['roam'] and self.walking and not stopped
        self.moving_now = move
        self.phase += dt * (11 if move else 2.3)
        if move:
            area = self.area()
            self.float_x += self.direction * self.c.store.effective_settings['speed'] * dt
            right = area.right() - self.width() + 1
            if self.float_x <= area.left() or self.float_x >= right:
                self.direction *= -1
                self.float_x = max(area.left(), min(self.float_x, right))
            self.move(round(self.float_x), self.base_y)
        bob = 0 if self.pressed else round((math.sin(self.phase) + 1) * (3.5 if move else 1.2))
        self.update_visual(bob)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.last_interaction = time.monotonic()
            self.moving_now = False
            self.pressed = True
            self.dragged = False
            self.start = e.globalPosition().toPoint()
            self.offset = self.start - self.pos()
            self.setCursor(Qt.ClosedHandCursor)
            self.expression('curious', 2)

    def mouseMoveEvent(self, e):
        if self.pressed:
            if (e.globalPosition().toPoint() - self.start).manhattanLength() > 6:
                self.dragged = True
            if self.dragged:
                self.move(e.globalPosition().toPoint() - self.offset)
                self.base_y = self.y()
                self.float_x = float(self.x())
                self.expression('confused', 1)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.pressed:
            self.pressed = False
            self.setCursor(Qt.OpenHandCursor)
            self.bounce_start = time.monotonic()
            self.ensure_visible()
            self.next_action = time.monotonic() + 4
            if self.dragged:
                self.expression('blushing shyly', 3)
            else:
                self.expression('excited', 5)
                self.c.toggle_chat()

    def enterEvent(self, e):
        self.hovered = True
        self.last_interaction = time.monotonic()
        self.moving_now = False
    def leaveEvent(self, e):
        self.hovered = False
    def contextMenuEvent(self, e):
        self.c.menu().exec(e.globalPos())
    def closeEvent(self, e):
        self.hide()
        e.ignore()


class Controller:
    def __init__(self, store=None, with_tray=True):
        self.store = store or Store()
        self.vaults = {pid: KeyVault(self.store.root, pid) for pid in PROVIDERS}
        self.busy = False
        self.pending = None
        self.summary_end = None
        self.demo_timer = QTimer()
        self.demo_timer.setSingleShot(True)
        self.demo_timer.timeout.connect(self.demo_done)
        self.chat = ChatWindow(self)
        self.client = ChatClient(self.chat)
        self.client.answered.connect(self.on_answer)
        self.client.failed.connect(self.on_error)
        self.folder_root = None
        from folder_agent import FolderAgent
        self.folder_agent = FolderAgent(self)
        self.folder_agent.done.connect(self.on_answer)
        self.pet = PetWindow(self)
        self.stocks = StockWindow(self)
        self.tray = None
        if with_tray and QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(QIcon(str(ASSETS / 'Izuna.cozy.webp')), self.chat)
            self.tray.setToolTip('이즈나 · 클릭해서 대화')
            self.traymenu = self.menu()
            self.traymenu.aboutToShow.connect(self.sync_tray_menu)
            self.tray.setContextMenu(self.traymenu)
            self.tray.activated.connect(self.tray_activated)
            self.tray.show()
        self.apply_appearance()
        self.pet.show()
        QApplication.instance().aboutToQuit.connect(self.shutdown)
        if self.vault.warning:
            self.chat.status.setText(self.vault.warning)
        self.startup_timer = QTimer(self.chat)
        self.startup_timer.setSingleShot(True)
        self.startup_timer.timeout.connect(self.open_chat)
        self.startup_timer.start(400)

    @property
    def vault(self):
        return self.vaults[self.store.settings['provider']]

    def persist(self):
        try:
            self.store.save()
        except OSError:
            self.chat.status.setText('설정을 PC에 저장하지 못했어요. 앱 폴더의 저장 권한을 확인해 주세요.')

    def open_chat(self):
        area = self.pet.area()
        saved = self.store.settings['window_geometry']
        valid = all(type(saved.get(k)) is int for k in ('x', 'y', 'width', 'height'))
        if valid:
            target = QApplication.screenAt(QPoint(saved['x'], saved['y']))
            if target:
                area = target.availableGeometry()
        self.chat.resize(min(max(420, saved['width'] if valid else 560), area.width()), min(max(360, saved['height'] if valid else 680), area.height()))
        x = saved['x'] if valid else self.pet.x() - self.chat.width() - 12
        if not valid and x < area.left():
            x = self.pet.x() + self.pet.width() + 12
        y = saved['y'] if valid else self.pet.y() + self.pet.height() - self.chat.height()
        self.chat.move(clamp_position(QPoint(x, y), self.chat.size(), area))
        self.chat.show()
        self.chat.raise_()
        self.chat.activateWindow()
        self.chat.input.setFocus()

    def open_stocks(self):
        area = self.pet.area()
        scale = 1
        self.stocks.resize(min(round(850 * scale), area.width()), min(round(560 * scale), area.height()))
        self.stocks.move(clamp_position(QPoint(area.center().x() - self.stocks.width() // 2,
                                               area.center().y() - self.stocks.height() // 2),
                                        self.stocks.size(), area))
        self.stocks.show()
        self.stocks.raise_()
        self.stocks.activateWindow()

    @staticmethod
    def set_on_top(window, enabled):
        visible = window.isVisible()
        position = window.pos()
        window.setWindowFlag(Qt.WindowStaysOnTopHint, enabled)
        window.move(position)
        if visible:
            window.show()

    def apply_appearance(self):
        settings = self.store.settings
        scale = 1
        self.chat.setMinimumSize(420, 360)
        self.stocks.setMinimumSize(round(680 * scale), round(440 * scale))
        self.chat.setWindowOpacity(settings['interface_opacity'] / 100)
        self.stocks.setWindowOpacity(settings['interface_opacity'] / 100)
        self.pet.setWindowOpacity(settings['pet_opacity'] / 100)
        self.set_on_top(self.pet, settings['pet_on_top'])
        self.set_on_top(self.chat, settings['chat_on_top'])
        self.set_on_top(self.stocks, settings['chat_on_top'])
        self.pet.reload_size()
        self.chat.refresh_status()

    def toggle_chat(self):
        if self.chat.isVisible():
            self.chat.hide()
        else:
            self.open_chat()

    def tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self.pet.show()
            self.open_chat()

    def choose_folder(self):
        if self.busy: return
        root=QFileDialog.getExistingDirectory(self.chat, '이즈나가 작업할 폴더 선택')
        if not root: return
        if QMessageBox.question(self.chat, '폴더 작업 연결', '선택한 폴더: '+root+'\n\n이 모드의 채팅은 이 폴더를 대상으로 합니다. 파일 이름과 읽은 텍스트가 선택한 AI 서비스로 전송됩니다. 이동·저장은 계획 확인 후 실행합니다.\n연결할까요?') != QMessageBox.Yes: return
        self.folder_root=root
        self.chat.folder_indicator.setText('폴더 작업: '+Path(root).name+' · 클릭하여 종료')
        self.chat.folder_indicator.setToolTip(root)
        self.chat.folder_indicator.show()
        self.chat.input.setPlaceholderText('폴더 작업: 정리하고 감상.txt로 저장해줘')
        self.chat.status.setText('폴더 작업 모드 · '+root+' · 종료: ⋯ 메뉴')

    def clear_folder(self):
        if self.busy: return
        self.folder_root=None
        self.chat.folder_indicator.hide()
        self.chat.input.setPlaceholderText('메시지를 입력하세요')
        self.chat.status.setText('폴더 작업을 종료했어요.')

    def send(self, text):
        text = text.strip()[:4000]
        if not text or self.busy:
            return False
        if self.folder_root and self.store.settings['demo']:
            self.chat.status.setText('폴더 작업에는 실제 AI 연결이 필요해요. 설정에서 데모를 끄고 API를 연결하세요.')
            return False
        if not self.store.settings['demo'] and self.store.settings['provider'] != 'ollama' and not self.vault.session_key:
            self.chat.status.setText('설정에서 API 키를 입력해 주세요.')
            self.open_settings()
            return False
        self.summary_end = None
        self.pending = {'role': 'user', 'content': text}
        self.chat.add_message('user', text)
        self.busy = True
        self.chat.set_busy(True)
        self.pet.expression('thinking', 185)
        if self.folder_root:
            self.folder_agent.start(self.folder_root,text)
        elif self.store.settings['demo']:
            self.demo_timer.start(650)
        else:
            self.continue_request()
        return self.pending is not None

    def continue_request(self):
        chat = self.store.active_chat
        self.summary_end = summary_target(chat)
        if self.summary_end is not None:
            payload = build_summary_payload(self.store.effective_settings, chat, self.summary_end)
            self.chat.status.setText('오래된 대화를 장기 기억으로 정리하고 있어요…')
        else:
            self.chat.status.setText(CHARACTERS[self.store.character]['name'] + '가 생각하고 있어요…')
            payload = build_payload(self.store.effective_settings, self.store.history[chat['summary_until']:] + [self.pending])
        self.client.send(self.vault.session_key, payload, self.store.settings['provider'], self.store.settings['ollama_url'])

    def demo_done(self):
        if self.pending is not None:
            self.on_answer(*demo_reply(self.pending['content'], self.store.effective_settings['nickname'], self.store.character))

    def on_answer(self, text, emotion):
        if self.pending is None:
            return
        if self.summary_end is not None:
            if not text.strip() or len(text) > 6000 or emotion != 'thinking':
                self.on_error('장기 기억 요약 형식이 맞지 않아요. 원문은 보존했으니 다시 보내 주세요.')
                return
            self.store.active_chat.update(summary=text, summary_until=self.summary_end)
            self.summary_end = None
            self.persist()
            self.continue_request()
            return
        self.store.history.extend([self.pending, {'role': 'assistant', 'content': text, 'character': self.store.character}])
        self.store.active_chat['updated_at'] = datetime.now().astimezone().isoformat()
        if self.store.active_chat['title'] == '새 대화':
            self.store.active_chat['title'] = self.pending['content'][:16]
            self.chat.tabs.setTabText(self.chat.tabs.currentIndex(), self.store.active_chat['title'])
        self.chat.refresh_status()
        self.store.active_chat['draft'] = ''
        self.pending = None
        self.busy = False
        self.chat.set_busy(False)
        self.chat.add_message('assistant', text)
        self.pet.expression(emotion, 12)
        self.persist()
        if not self.chat.isVisible() and self.tray:
            self.tray.setToolTip('이즈나 · 답변이 도착했어요')

    def on_error(self, message):
        if self.pending:
            self.chat.input.setText(self.pending['content'])
        self.summary_end = None
        self.pending = None
        self.chat.reset_messages()
        self.busy = False
        self.chat.set_busy(False)
        self.chat.status.setText(message)
        self.pet.expression('confused', 8)

    def cancel(self):
        if not self.folder_agent.cancel(): return
        self.demo_timer.stop()
        self.client.cancel()
        if self.pending:
            self.chat.input.setText(self.pending['content'])
        self.summary_end = None
        self.pending = None
        self.chat.reset_messages()
        self.busy = False
        self.chat.set_busy(False)
        self.chat.status.setText('답변 받기를 중지했어요. 이미 처리된 API 사용량은 청구될 수 있어요.')
        self.pet.expression('cozy', 3)

    def open_settings(self):
        if self.busy:
            self.chat.status.setText('답변을 기다리거나 중지한 뒤 설정을 열어 주세요.')
            return
        self.chat.save_draft()
        self.pet.settings_open = True
        try:
            SettingsDialog(self).exec()
        finally:
            self.pet.settings_open = False

    def toggle_roam(self):
        self.store.settings['roam'] = not self.store.settings['roam']
        self.persist()

    def hide_pet(self):
        if self.pet.isVisible():
            self.pet.hide()
            self.chat.hide()
        else:
            self.pet.show()
            self.pet.ensure_visible()

    def sync_tray_menu(self):
        for action in self.traymenu.actions():
            if action.data() == 'roam':
                action.setChecked(self.store.settings['roam'])
            elif action.data() == 'visibility':
                action.setText('캐릭터 숨기기' if self.pet.isVisible() else '캐릭터 보이기')

    def menu(self):
        menu = QMenu()
        menu.addAction('캐릭터와 대화', self.open_chat)
        menu.addAction('주식 · 포트폴리오', self.open_stocks)
        menu.addAction('설정', self.open_settings)
        menu.addSeparator()
        walk = menu.addAction('자동 산책')
        walk.setData('roam')
        walk.setCheckable(True)
        walk.setChecked(self.store.settings['roam'])
        walk.triggered.connect(self.toggle_roam)
        moods = menu.addMenu('표정 바꾸기')
        items = list(EMOTIONS.items())
        for i in range(0, len(items), 12):
            group = moods.addMenu(f'표정 {i+1}–{min(i+12, len(items))}')
            for key, title in items[i:i+12]:
                group.addAction(title, lambda e=key: self.pet.expression(e, 20))
        menu.addAction('화면 아래로 내려오기', self.to_floor)
        # Hiding is only available when a tray icon can bring the pet back.
        if self.tray is not None:
            action = menu.addAction('캐릭터 숨기기' if self.pet.isVisible() else '캐릭터 보이기', self.hide_pet)
            action.setData('visibility')
        menu.addSeparator()
        menu.addAction('종료', QApplication.instance().quit)
        return menu

    def to_floor(self):
        self.pet.move(self.pet.x(), self.pet.area().bottom() - self.pet.height() + 1)
        self.pet.ensure_visible()

    def shutdown(self):
        self.folder_agent.cancel()
        self.chat.save_geometry()
        self.startup_timer.stop()
        self.chat.scroll_timer.stop()
        self.demo_timer.stop()
        self.client.cancel()
        self.stocks.market_client.cancel(emit=False)
        self.stocks.auto_timer.stop()
        self.pet.timer.stop()
        self.chat.save_draft()
        if self.pending:
            self.store.active_chat['draft'] = self.pending['content']
        self.persist()
        if self.tray:
            self.tray.hide()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName('IzunaDesktop')
    app.setOrganizationName('IzunaDesktop')
    app.setQuitOnLastWindowClosed(False)
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    app.setWindowIcon(QIcon(str(ASSETS / 'Izuna.cozy.webp')))
    store = Store()
    lock = QLockFile(str(store.root / 'app.lock'))
    if not lock.tryLock(0):
        QMessageBox.information(None, '이즈나', '이미 실행 중이에요. 작업 표시줄 오른쪽의 이즈나 아이콘을 눌러 주세요.')
        return 0
    if not (ASSETS / 'Izuna.cozy.webp').is_file():
        QMessageBox.critical(None, '이즈나', 'assets 폴더를 찾을 수 없어요. ZIP 전체를 압축 해제한 뒤 실행해 주세요.')
        return 1
    controller = Controller(store)
    code = app.exec()
    lock.unlock()
    return code


if __name__ == '__main__':
    sys.exit(main())
