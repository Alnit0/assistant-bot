import asyncio
from types import SimpleNamespace

import pytest

from core import devmode, lifecycle
from core.config import CONFIRMATION_SECONDS
from core.context import Context
from core.lifecycle import MessageClass
from skills.timers import store

EVERY_CLASS = list(MessageClass)


# --- the policy --------------------------------------------------------------
def test_there_are_six_classes_and_each_has_a_policy():
    assert [item.value for item in EVERY_CLASS] == ["Kept", "Live", "Consumed", "Transient", "Alert", "Protected"]
    assert set(lifecycle.POLICY) == set(EVERY_CLASS)
    for policy in lifecycle.POLICY.values():
        assert policy.examples and policy.what_happens


def test_kept_and_protected_messages_are_never_deleted_by_the_bot():
    assert not lifecycle.may_auto_delete(MessageClass.KEPT)
    assert not lifecycle.may_auto_delete(MessageClass.PROTECTED)


@pytest.mark.parametrize(
    "message_class", [MessageClass.LIVE, MessageClass.CONSUMED, MessageClass.TRANSIENT, MessageClass.ALERT]
)
def test_the_rest_may_go_once_their_information_lives_elsewhere(message_class):
    assert lifecycle.may_auto_delete(message_class)


@pytest.mark.parametrize("message_class", EVERY_CLASS)
def test_with_cleanup_off_nothing_is_deleted(message_class):
    assert not lifecycle.may_auto_delete(message_class, cleanup_on=False)


# --- which class a message is ------------------------------------------------
def test_content_is_kept():
    assert lifecycle.classify() is MessageClass.KEPT


def test_protection_overrides_everything():
    assert (
        lifecycle.classify(protected=True, declared=MessageClass.ALERT, transient=True, command=True)
        is MessageClass.PROTECTED
    )


def test_what_a_skill_declares_comes_next():
    assert lifecycle.classify(declared=MessageClass.LIVE, transient=True, command=True) is MessageClass.LIVE
    assert lifecycle.classify(declared=MessageClass.ALERT) is MessageClass.ALERT


def test_a_note_still_on_screen_is_transient_and_a_command_is_consumed():
    assert lifecycle.classify(transient=True) is MessageClass.TRANSIENT
    assert lifecycle.classify(command=True) is MessageClass.CONSUMED


def test_describe_names_the_class_and_what_happens():
    assert lifecycle.describe(MessageClass.TRANSIENT) == "Transient: deletes itself after a few seconds"
    assert lifecycle.describe(MessageClass.KEPT).startswith("Kept: never auto-deleted")


def test_transient_notes_are_remembered():
    lifecycle.note_transient(4242)
    lifecycle.note_transient(None)
    assert lifecycle.is_transient(4242)
    assert not lifecycle.is_transient(4243)


# --- dev cleanup off ---------------------------------------------------------
def test_cleanup_is_on_unless_dev_mode_switches_it_off(dev_off):
    assert lifecycle.deletes(MessageClass.CONSUMED)
    assert lifecycle.delete_after() == CONFIRMATION_SECONDS
    assert lifecycle.delete_after(15) == 15

    devmode.enable()
    assert lifecycle.deletes(MessageClass.TRANSIENT), "dev mode alone changes nothing"
    devmode.set_cleanup(False)
    for message_class in EVERY_CLASS:
        assert not lifecycle.deletes(message_class)
    assert lifecycle.delete_after() is None

    devmode.disable()
    assert lifecycle.deletes(MessageClass.ALERT), "switching dev mode off brings clean-up back"


class FakeChannel:
    def __init__(self):
        self.sent = []

    async def send(self, text, **options):
        self.sent.append((text, options))
        return SimpleNamespace(id=1000 + len(self.sent))


class FakeMessage:
    def __init__(self):
        self.deleted = False

    async def delete(self):
        self.deleted = True


def make_ctx(owner) -> tuple[Context, FakeChannel, FakeMessage]:
    channel, message = FakeChannel(), FakeMessage()
    return Context(owner, 100, 5, "ping", channel, _message=message), channel, message


def test_confirmations_and_commands_are_tidied_away(dev_off, owner):
    ctx, channel, message = make_ctx(owner)
    asyncio.run(ctx.confirm("📦 Archived"))
    asyncio.run(ctx.note("-# Read as: stats"))
    assert [options for _, options in channel.sent] == [{"delete_after": CONFIRMATION_SECONDS}] * 2
    assert lifecycle.is_transient(1001) and lifecycle.is_transient(1002)
    assert asyncio.run(ctx.delete_command()) is True
    assert message.deleted


def test_with_cleanup_off_they_stay(dev_off, owner):
    devmode.enable()
    devmode.set_cleanup(False)
    ctx, channel, message = make_ctx(owner)
    asyncio.run(ctx.confirm("📦 Archived"))
    assert channel.sent == [("📦 Archived", {"delete_after": None})]
    assert asyncio.run(ctx.delete_command()) is False
    assert not message.deleted


def test_lasting_replies_are_never_given_a_lifetime(dev_off, owner):
    ctx, channel, _ = make_ctx(owner)
    asyncio.run(ctx.reply("📋 No active timers."))
    assert channel.sent == [("📋 No active timers.", {})]


# --- what the timers skill declares ------------------------------------------
def timer(**values) -> store.Timer:
    return store.Timer(user_id=1, discord_user_id=1, channel_id=100, label="Tea", duration_s=60, **values)


def test_a_running_timer_is_live_and_its_alert_is_an_alert():
    running = timer(message_id=10)
    assert store.message_class_of(running, 10) is MessageClass.LIVE
    finished = timer(message_id=10, notice_message_id=11, status=store.FINISHED)
    assert store.message_class_of(finished, 11) is MessageClass.ALERT


def test_a_finished_timers_summary_is_ordinary_content():
    finished = timer(message_id=10, status=store.FINISHED)
    assert store.message_class_of(finished, 10) is None
    assert store.message_class_of(None, 10) is None
