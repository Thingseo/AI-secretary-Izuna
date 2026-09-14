"""Nonblocking HTTPS client; credentials stay in the local process."""
import json
from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from providers import build_request, parse_provider_response

class ChatClient(QObject):
    answered = Signal(str, str)
    failed = Signal(str)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.manager = QNetworkAccessManager(self)
        self.reply = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._timeout)

    def send(self, key, payload, provider="openai", base="http://localhost:11434"):
        if self.reply is not None:
            return
        try:
            url, headers, payload = build_request(provider, key, payload, base)
        except ValueError as exc:
            self.failed.emit(str(exc))
            return
        self.provider = provider
        request = QNetworkRequest(QUrl(url))
        request.setHeader(QNetworkRequest.ContentTypeHeader, 'application/json')
        for name, value in headers.items():
            request.setRawHeader(name.encode('ascii'), value.encode('utf-8'))
        request.setAttribute(QNetworkRequest.RedirectPolicyAttribute, QNetworkRequest.ManualRedirectPolicy)
        reply = self.manager.post(request, json.dumps(payload, ensure_ascii=False).encode('utf-8'))
        self.reply = reply
        reply.finished.connect(lambda: self._finished(reply))
        self.timeout_ms = 180000 if provider == "ollama" else 90000
        self.timer.start(self.timeout_ms)

    def cancel(self):
        self.timer.stop()
        reply, self.reply = self.reply, None
        if reply is not None:
            reply.abort()  # finished handler disposes reply; stale results are ignored.

    def _timeout(self):
        self.cancel()
        self.failed.emit(f'{self.timeout_ms // 1000}초 안에 답변을 받지 못했어요. 서버 상태와 모델 로딩을 확인해 주세요.')

    def _finished(self, reply):
        if reply is not self.reply:
            reply.deleteLater()
            return
        self.reply = None
        self.timer.stop()
        status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        raw = bytes(reply.readAll())
        error = reply.error()
        reply.deleteLater()
        if status != 200:
            messages = {
                400: '요청을 처리할 수 없어요. 모델 이름과 선택한 서비스의 지원 여부를 확인해 주세요.',
                401: 'API 키가 올바르지 않아요. 설정에서 키를 다시 입력해 주세요.',
                403: '이 API 키에 사용 권한이 없어요. 선택한 서비스의 프로젝트 권한을 확인해 주세요.',
                404: '모델을 찾지 못했어요. 설정에서 사용 가능한 모델 이름을 입력해 주세요.',
                429: 'API 한도 또는 결제 잔액을 확인해 주세요. 잠시 후 다시 시도할 수도 있어요.',
            }
            message = messages.get(status, 'API 서버 응답 오류예요. 잠시 후 다시 보내 주세요.' if status else '연결하지 못했어요. 인터넷과 방화벽 설정을 확인해 주세요.')
            self.failed.emit(message)
            return
        try:
            text, emotion = parse_provider_response(self.provider, json.loads(raw))
        except (ValueError, TypeError, AttributeError, KeyError) as exc:
            self.failed.emit(str(exc) if isinstance(exc, ValueError) and not isinstance(exc, json.JSONDecodeError) else '응답을 읽지 못했어요. 다시 시도해 주세요.')
            return
        self.answered.emit(text, emotion)

class ModelCatalog(QObject):
    loaded = Signal(list)
    failed = Signal(str)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.manager = QNetworkAccessManager(self)
        self.reply = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.timeout)

    def fetch(self, provider, base, key=''):
        from providers import ollama_base
        self.cancel()
        try:
            url = ollama_base(base) + '/api/tags' if provider == 'ollama' else 'https://ai-gateway.vercel.sh/v1/models'
        except ValueError as e:
            self.failed.emit(str(e)); return
        req = QNetworkRequest(QUrl(url))
        req.setAttribute(QNetworkRequest.RedirectPolicyAttribute, QNetworkRequest.ManualRedirectPolicy)
        if provider == 'ollama' and key:
            req.setRawHeader(b'Authorization', ('Bearer ' + key).encode())
        reply = self.manager.get(req)
        self.reply = reply
        reply.finished.connect(lambda: self.finish(reply, provider))
        self.timer.start(15000)

    def cancel(self):
        self.timer.stop()
        reply, self.reply = self.reply, None
        if reply is not None:
            reply.abort()

    def timeout(self):
        self.cancel()
        self.failed.emit('모델 목록 요청 시간이 초과됐어요. 기본 목록이나 직접 입력을 사용해 주세요.')

    def finish(self, reply, provider):
        if reply is not self.reply:
            reply.deleteLater(); return
        self.reply = None
        self.timer.stop()
        try:
            if reply.attribute(QNetworkRequest.HttpStatusCodeAttribute) != 200:
                raise ValueError()
            data = json.loads(bytes(reply.readAll()))
            if provider == 'ollama':
                names = [m['name'] for m in data.get('models', []) if isinstance(m.get('name'), str)]
            else:
                names = [m['id'] for m in data.get('data', []) if isinstance(m.get('id'), str) and m.get('type', 'language') == 'language']
            self.loaded.emit(sorted(set(names)))
        except (ValueError, TypeError, KeyError):
            self.failed.emit('목록을 가져오지 못했어요. 서버 실행 여부를 확인하거나 직접 입력해 주세요.')
        finally:
            reply.deleteLater()
