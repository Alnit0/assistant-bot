import tests  # noqa: F401  isort: skip  (first: sets safe test settings before core loads)

import unittest
from types import SimpleNamespace

from core import database, reactions
from core.protection import is_protected, protection
from core.reactions import emoji_key, final_states, plan_changes
from tests.helpers import DatabaseTestCase

# A reaction action is (message id, emoji, user id)
PIN, STAR = (10, "📌", 1), (10, "⭐", 1)
OTHER_MESSAGE = (20, "📌", 1)


def plan(events, applied=()):
    """What would be applied and undone after these (key, added) events."""
    return plan_changes(final_states(events), set(applied))


class FinalStateTest(unittest.TestCase):
    def test_added(self):
        self.assertEqual(plan([(PIN, True)]), ([PIN], []))

    def test_added_then_removed_in_time_does_nothing(self):
        self.assertEqual(plan([(PIN, True), (PIN, False)]), ([], []))

    def test_only_where_it_ended_up_matters(self):
        self.assertEqual(plan([(PIN, True), (PIN, False), (PIN, True)]), ([PIN], []))
        self.assertEqual(plan([(PIN, True), (PIN, False), (PIN, True), (PIN, False)]), ([], []))

    def test_removing_an_applied_reaction_undoes_it(self):
        self.assertEqual(plan([(PIN, False)], applied=[PIN]), ([], [PIN]))

    def test_removing_and_putting_back_an_applied_reaction_does_nothing(self):
        self.assertEqual(plan([(PIN, False), (PIN, True)], applied=[PIN]), ([], []))

    def test_adding_one_that_is_already_applied_does_not_apply_it_twice(self):
        self.assertEqual(plan([(PIN, True)], applied=[PIN]), ([], []))

    def test_removing_one_that_was_never_applied_does_nothing(self):
        self.assertEqual(plan([(PIN, False)]), ([], []))

    def test_each_emoji_and_message_is_judged_on_its_own(self):
        events = [(PIN, True), (STAR, True), (OTHER_MESSAGE, True), (STAR, False), (OTHER_MESSAGE, False)]
        self.assertEqual(plan(events), ([PIN], []))
        self.assertEqual(plan(events, applied=[OTHER_MESSAGE]), ([PIN], [OTHER_MESSAGE]))

    def test_untouched_reactions_are_left_alone(self):
        # ⭐ is applied but nobody touched it in this burst
        self.assertEqual(plan([(PIN, True)], applied=[STAR]), ([PIN], []))

    def test_different_users_are_separate(self):
        mine, theirs = (10, "📌", 1), (10, "📌", 2)
        self.assertEqual(plan([(mine, True), (theirs, True), (theirs, False)]), ([mine], []))

    def test_emoji_are_compared_without_the_invisible_style_character(self):
        self.assertEqual(emoji_key("🗑️"), emoji_key("🗑"))
        self.assertEqual(emoji_key("📦"), "📦")


class AppliedStateTest(DatabaseTestCase):
    async def test_applied_actions_are_remembered_and_forgotten(self):
        self.assertEqual(await database.run(reactions.db_applied, [10, 20]), set())
        await database.run(reactions.db_mark_applied, PIN, 100)
        await database.run(reactions.db_mark_applied, STAR, 100)
        await database.run(reactions.db_mark_applied, PIN, 100)  # twice is harmless
        await database.run(reactions.db_mark_applied, OTHER_MESSAGE, 100)
        self.assertEqual(await database.run(reactions.db_applied, [10]), {PIN, STAR})
        self.assertEqual(await database.run(reactions.db_applied, [10, 20]), {PIN, STAR, OTHER_MESSAGE})
        self.assertEqual(await database.run(reactions.db_applied, []), set())

        self.assertEqual(await database.run(reactions.db_forget, PIN), 1, "⭐ is still applied on that message")
        self.assertEqual(await database.run(reactions.db_forget, STAR), 0, "nothing left: the ✅ can go")
        self.assertEqual(await database.run(reactions.db_applied, [10, 20]), {OTHER_MESSAGE})

    async def test_it_survives_a_restart_because_it_is_in_the_database(self):
        await database.run(reactions.db_mark_applied, PIN, 100)
        # A new process knows nothing but what the database says
        applied = await database.run(reactions.db_applied, [10])
        self.assertEqual(plan([(PIN, False)], applied), ([], [PIN]))


def message(pinned=False, emoji=()):
    return SimpleNamespace(pinned=pinned, reactions=[SimpleNamespace(emoji=e, count=n) for e, n in emoji])


class ProtectionTest(unittest.TestCase):
    def test_ordinary_messages_are_not_protected(self):
        self.assertFalse(is_protected(message()))
        self.assertFalse(is_protected(message(emoji=[("👍", 3), ("📦", 1)])))
        self.assertIsNone(protection(message()))

    def test_pinned(self):
        self.assertEqual(protection(message(pinned=True)), "pinned")

    def test_marked_with_a_pin_by_anyone(self):
        self.assertEqual(protection(message(emoji=[("👍", 1), ("📌", 1)])), "marked 📌")
        self.assertTrue(is_protected(message(emoji=[("📌", 4)])))

    def test_a_pin_reaction_that_has_been_removed_no_longer_protects(self):
        self.assertFalse(is_protected(message(emoji=[("📌", 0)])))

    def test_objects_without_those_details_are_not_protected(self):
        self.assertFalse(is_protected(SimpleNamespace()))


if __name__ == "__main__":
    unittest.main()
