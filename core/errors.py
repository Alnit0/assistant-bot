class UserError(Exception):
    """Something went wrong that the user can fix. The message is shown to them as is.

    Raise it from a handler for things like bad arguments or a missing
    permission. It is reported without a traceback.
    """
