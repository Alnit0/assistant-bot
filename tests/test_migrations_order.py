"""The core migrations are only ever appended: a database at version N has run the first N of them, so
one put anywhere but the end runs out of order on every database that exists (found 16 Oct: live did not
start). The first 25 are live's, as they stood on 16 Oct, by name and in order."""
from core import migrations

LIVE_ON_16_OCT = (
    "_create_message_log", "_create_users", "_add_user_id_to_message_log", "_create_skill_migrations",
    "_create_scheduled_jobs", "_create_reaction_state", "_add_timing_to_message_log", "_create_occurrences",
    "_add_cost_logging", "_create_confirm_cards", "_create_live_lists", "_add_task_to_live_lists",
    "_add_previous_to_confirm_cards", "_add_trace_to_message_log", "_add_cause_to_occurrences",
    "_add_confirmation_to_confirm_cards", "_add_question_to_confirm_cards", "_create_spend_notices",
    "_create_schedules", "_create_bot_messages", "_create_missed_messages", "_create_held_alerts",
    "_add_ended_to_bot_alive", "_create_needs_look", "_create_exchange_rates",
)


def test_the_migrations_a_database_has_run_keep_their_places():
    names = tuple(each.__name__ for each in migrations.MIGRATIONS)
    assert names[: len(LIVE_ON_16_OCT)] == LIVE_ON_16_OCT, "a migration is appended at the end, never put in between"
    assert len(set(names)) == len(names)
