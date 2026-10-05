import re

import pytest
from fastapi.testclient import TestClient

from beismart import mailer as mailer_module
from beismart.api import create_app
from beismart.mailer import MailError, OutboxMailer, get_mailer


class FakeMailer:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def send(self, to, subject, text, html=None):
        if self.fail:
            raise MailError("down")
        self.sent.append({"to": to, "subject": subject, "text": text, "html": html})


@pytest.fixture
def mail():
    return FakeMailer()


@pytest.fixture
def client(mail):
    with TestClient(create_app(":memory:", stores=[], mailer=mail, base_url="http://app.test")) as c:
        yield c


BODY = {"query": "samsung tv", "target_price": 30000, "email": "ben@example.com"}


def link(message, action):
    return re.search(rf"http://app\.test/api/watches/{action}\?token=[\w-]+", message["text"]).group(0)


# ── creating and confirming ───────────────────────────────────────────────────

def test_creating_a_watch_sends_one_confirmation_email(client, mail):
    r = client.post("/api/watches", json=BODY)
    assert r.status_code == 202 and r.json()["status"] == "confirmation_sent"
    assert len(mail.sent) == 1 and mail.sent[0]["to"] == "ben@example.com"
    assert "KSh 30,000" in mail.sent[0]["text"] and "samsung tv" in mail.sent[0]["subject"]


def test_the_response_never_contains_the_secret_token(client, mail):
    body = client.post("/api/watches", json=BODY).text
    token = link(mail.sent[0], "confirm").split("token=")[1]
    assert token not in body


def test_nothing_is_active_until_the_link_is_opened(client, mail):
    client.post("/api/watches", json=BODY)
    assert client.app.state.conn.execute("SELECT confirmed FROM watches").fetchone()[0] == 0
    page = client.get(link(mail.sent[0], "confirm").replace("http://app.test", ""))
    assert page.status_code == 200 and "Your price alert is on" in page.text
    assert client.app.state.conn.execute("SELECT confirmed FROM watches").fetchone()[0] == 1


def test_asking_twice_quickly_does_not_send_a_second_email(client, mail):
    client.post("/api/watches", json=BODY)
    again = client.post("/api/watches", json={**BODY, "target_price": 28000})
    assert again.json()["status"] == "waiting_for_confirmation" and len(mail.sent) == 1


def test_a_confirmed_watch_just_gets_its_target_updated(client, mail):
    client.post("/api/watches", json=BODY)
    client.get(link(mail.sent[0], "confirm").replace("http://app.test", ""))
    r = client.post("/api/watches", json={**BODY, "target_price": 25000})
    assert r.json()["status"] == "updated" and "25,000" in r.json()["message"] and len(mail.sent) == 1


@pytest.mark.parametrize("change", [{"email": "nope"}, {"target_price": 0}, {"target_price": -1}, {"query": "a"}, {"email": ""}])
def test_bad_input_is_rejected_and_nothing_is_sent(client, mail, change):
    assert client.post("/api/watches", json={**BODY, **change}).status_code == 422
    assert mail.sent == []


def test_when_the_email_cannot_be_sent_the_caller_is_told(client):
    with TestClient(create_app(":memory:", stores=[], mailer=FakeMailer(fail=True), base_url="http://app.test")) as c:
        r = c.post("/api/watches", json=BODY)
        assert r.status_code == 502 and "could not send" in r.json()["detail"].lower()


def test_mail_bombing_one_address_is_stopped(client, mail):
    for i in range(5):
        assert client.post("/api/watches", json={**BODY, "query": f"thing {i}"}).status_code == 202
    assert client.post("/api/watches", json={**BODY, "query": "sixth"}).status_code == 429       # per-address or per-IP limit


def test_one_client_cannot_ask_for_endless_confirmation_emails(client, mail):
    codes = [client.post("/api/watches", json={**BODY, "email": f"p{i}@example.com"}).status_code for i in range(7)]
    assert codes[:5] == [202] * 5 and codes[5:] == [429, 429]
    assert len(mail.sent) == 5


# ── the pages opened from emails ──────────────────────────────────────────────

def test_an_invalid_link_gets_a_friendly_404(client):
    for action in ("confirm", "manage", "unsubscribe"):
        r = client.get(f"/api/watches/{action}", params={"token": "nope"})
        assert r.status_code == 404 and "not valid" in r.text


def test_opening_the_unsubscribe_link_does_not_delete_anything(client, mail):
    client.post("/api/watches", json=BODY)
    url = link(mail.sent[0], "unsubscribe").replace("http://app.test", "")
    page = client.get(url)                              # what an email scanner that opens links would do
    assert "Remove this alert?" in page.text
    assert client.app.state.conn.execute("SELECT COUNT(*) FROM watches").fetchone()[0] == 1


def test_pressing_the_button_removes_the_watch_once(client, mail):
    client.post("/api/watches", json=BODY)
    url = link(mail.sent[0], "unsubscribe").replace("http://app.test", "")
    assert "Alert removed" in client.post(url).text
    assert client.app.state.conn.execute("SELECT COUNT(*) FROM watches").fetchone()[0] == 0
    assert client.post(url).status_code == 404


def test_the_manage_page_lists_the_persons_alerts_and_can_remove_each(client, mail):
    client.post("/api/watches", json=BODY)
    client.post("/api/watches", json={**BODY, "query": "fridge"})
    page = client.get(link(mail.sent[0], "confirm").replace("confirm", "manage").replace("http://app.test", ""))
    assert "samsung tv" in page.text and "fridge" in page.text and page.text.count("Remove") == 2


def test_product_names_from_stores_cannot_inject_html(client, mail):
    evil = '<script>alert(1)</script>"><img src=x>'
    client.post("/api/watches", json={**BODY, "label": evil})
    message = mail.sent[0]
    assert "<script>" not in message["html"] and "&lt;script&gt;" in message["html"]
    manage = client.get(link(message, "confirm").replace("confirm", "manage").replace("http://app.test", ""))
    assert "<script>" not in manage.text and "&lt;script&gt;" in manage.text
    confirmed = client.get(link(message, "confirm").replace("http://app.test", ""))
    assert "<script>" not in confirmed.text


# ── the mailer ────────────────────────────────────────────────────────────────

def test_the_outbox_mailer_writes_messages_to_files_and_sends_nothing(tmp_path):
    OutboxMailer(str(tmp_path)).send("a@b.co", "Hello there", "plain body", "<p>html body</p>")
    names = sorted(p.name for p in tmp_path.iterdir())
    assert len(names) == 2 and names[0].endswith("hello-there.html") or names[0].endswith("hello-there.txt")
    text = next(p for p in tmp_path.iterdir() if p.suffix == ".txt").read_text(encoding="utf-8")
    assert "To: a@b.co" in text and "plain body" in text


def test_two_messages_in_the_same_second_do_not_overwrite_each_other(tmp_path):
    box = OutboxMailer(str(tmp_path))
    box.send("a@b.co", "Same subject", "first")
    box.send("a@b.co", "Same subject", "second")
    assert len(list(tmp_path.glob("*.txt"))) == 2


def test_the_default_mailer_is_the_safe_outbox(monkeypatch):
    monkeypatch.delenv("BEISMART_MAIL", raising=False)
    assert isinstance(get_mailer(), OutboxMailer)


def test_smtp_mode_without_settings_fails_loudly_rather_than_silently(monkeypatch):
    monkeypatch.setenv("BEISMART_MAIL", "smtp")
    for name in ("BEISMART_SMTP_HOST", "BEISMART_SMTP_USER", "BEISMART_SMTP_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(MailError):
        get_mailer()


def test_smtp_mode_with_settings_builds_an_smtp_mailer(monkeypatch):
    monkeypatch.setenv("BEISMART_MAIL", "smtp")
    monkeypatch.setenv("BEISMART_SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("BEISMART_SMTP_USER", "me@example.test")
    monkeypatch.setenv("BEISMART_SMTP_PASSWORD", "secret")
    assert isinstance(get_mailer(), mailer_module.SmtpMailer)
