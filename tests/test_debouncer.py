# tests/test_debouncer.py — buffer + flush combinado por chat

import asyncio
import importlib
import pytest

from agent import debouncer


@pytest.fixture(autouse=True)
def _short_debounce(monkeypatch):
    """Reduce el window a 0.2s para que los tests corran rapido."""
    monkeypatch.setenv("MESSAGE_DEBOUNCE_SEC", "0.2")
    importlib.reload(debouncer)
    yield
    debouncer.clear()


@pytest.mark.asyncio
async def test_single_message_flushed_with_count_1():
    received = []

    async def handler(chat_id, texto, mensaje_id, fue_audio, count):
        received.append((chat_id, texto, mensaje_id, fue_audio, count))

    debouncer.schedule("chat1", "hola", "id1", False, handler)
    await asyncio.sleep(0.4)

    assert len(received) == 1
    assert received[0] == ("chat1", "hola", "id1", False, 1)


@pytest.mark.asyncio
async def test_two_messages_combined_into_one_flush():
    received = []

    async def handler(chat_id, texto, mensaje_id, fue_audio, count):
        received.append((chat_id, texto, mensaje_id, count))

    debouncer.schedule("chat1", "primero", "id1", False, handler)
    await asyncio.sleep(0.1)  # menos que el debounce window
    debouncer.schedule("chat1", "segundo", "id2", False, handler)
    await asyncio.sleep(0.4)

    assert len(received) == 1
    assert received[0][1] == "primero\nsegundo"
    assert received[0][2] == "id2"  # ultimo mensaje_id
    assert received[0][3] == 2  # message_count


@pytest.mark.asyncio
async def test_three_messages_combined():
    received = []

    async def handler(chat_id, texto, mensaje_id, fue_audio, count):
        received.append((texto, count))

    for i in range(3):
        debouncer.schedule("chat1", f"msg{i}", f"id{i}", False, handler)
        await asyncio.sleep(0.05)

    await asyncio.sleep(0.4)

    assert len(received) == 1
    assert received[0][0] == "msg0\nmsg1\nmsg2"
    assert received[0][1] == 3


@pytest.mark.asyncio
async def test_messages_in_different_chats_dont_combine():
    received = []

    async def handler(chat_id, texto, mensaje_id, fue_audio, count):
        received.append((chat_id, texto))

    debouncer.schedule("chatA", "hola A", "idA", False, handler)
    debouncer.schedule("chatB", "hola B", "idB", False, handler)
    await asyncio.sleep(0.4)

    assert len(received) == 2
    by_chat = {chat: texto for chat, texto in received}
    assert by_chat["chatA"] == "hola A"
    assert by_chat["chatB"] == "hola B"


@pytest.mark.asyncio
async def test_messages_far_apart_each_flushes_separately():
    received = []

    async def handler(chat_id, texto, mensaje_id, fue_audio, count):
        received.append((texto, count))

    debouncer.schedule("chat1", "msg1", "id1", False, handler)
    await asyncio.sleep(0.4)
    debouncer.schedule("chat1", "msg2", "id2", False, handler)
    await asyncio.sleep(0.4)

    assert len(received) == 2
    assert received[0] == ("msg1", 1)
    assert received[1] == ("msg2", 1)


@pytest.mark.asyncio
async def test_any_audio_propagates_to_handler():
    received = []

    async def handler(chat_id, texto, mensaje_id, fue_audio, count):
        received.append(fue_audio)

    debouncer.schedule("chat1", "hola", "id1", False, handler)
    await asyncio.sleep(0.05)
    debouncer.schedule("chat1", "transcripcion", "id2", True, handler)
    await asyncio.sleep(0.4)

    assert received == [True]


@pytest.mark.asyncio
async def test_clear_cancels_pending():
    received = []

    async def handler(chat_id, texto, mensaje_id, fue_audio, count):
        received.append(texto)

    debouncer.schedule("chat1", "hola", "id1", False, handler)
    debouncer.clear()
    await asyncio.sleep(0.4)

    assert received == []
    assert debouncer.pending_count("chat1") == 0


@pytest.mark.asyncio
async def test_handler_exception_doesnt_crash():
    async def handler_fail(chat_id, texto, mensaje_id, fue_audio, count):
        raise ValueError("boom")

    debouncer.schedule("chat1", "hola", "id1", False, handler_fail)
    await asyncio.sleep(0.4)

    # Buffer limpio post-flush, no quedaron tasks colgadas
    assert debouncer.pending_count("chat1") == 0
