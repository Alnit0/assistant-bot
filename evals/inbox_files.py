"""Made-up files for the smart inbox's checks (evals/inbox.py) and tests: drawn here, the same every time, so
no real screenshot, bill or label is ever in the repository. Every name, date and number is invented."""
import io


def _drawn(lines: list[str], size=(520, 260)) -> "Image":
    from PIL import Image, ImageDraw, ImageFont

    made = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(made)
    try:
        font = ImageFont.load_default(size=22)
    except TypeError:  # an older Pillow
        font = ImageFont.load_default()
    for at, line in enumerate(lines):
        draw.text((20, 20 + at * 34), line, fill="black", font=font)
    return made


def _png(lines: list[str]) -> bytes:
    out = io.BytesIO()
    _drawn(lines).save(out, format="PNG")
    return out.getvalue()


def appointment() -> tuple[str, bytes, str]:
    """A screenshot of a booking confirmation."""
    return "screenshot.png", _png(["Booking confirmed", "Made-up Dental Clinic", "Thursday 5 November 2026", "3:00 pm, 45 minutes", "Reply C to cancel"]), "image/png"


def bill() -> tuple[str, bytes, str]:
    """A bill as a PDF: an image of the page, saved as a PDF."""
    out = io.BytesIO()
    _drawn(["Made-up Power Co", "Invoice 0001", "Amount due: $123.45", "Due date: 20 November 2026", "Pay online or by direct debit"], (620, 300)).save(out, format="PDF")
    return "bill.pdf", out.getvalue(), "application/pdf"


def label() -> tuple[str, bytes, str]:
    """A medicine label, for a made-up medicine."""
    return "label.jpg", _jpeg(["TESTVIT 10 mg tablets", "Take ONE tablet TWICE daily", "with food", "Made-up Pharmacy"]), "image/jpeg"


def _jpeg(lines: list[str]) -> bytes:
    out = io.BytesIO()
    _drawn(lines).save(out, format="JPEG", quality=90)
    return out.getvalue()


def gym_plan() -> tuple[str, bytes, str]:
    return "plan.csv", b"Day,Exercise,Sets,Reps\nMon,Squat,3,5\nMon,Bench press,3,5\nWed,Deadlift,1,5\nFri,Overhead press,3,8\n", "text/csv"


def shapes() -> tuple[str, bytes, str]:
    """Nothing worth keeping: a drawing of shapes."""
    from PIL import Image, ImageDraw

    made = Image.new("RGB", (300, 200), "white")
    draw = ImageDraw.Draw(made)
    draw.ellipse((40, 40, 140, 140), outline="blue", width=6)
    draw.rectangle((170, 60, 260, 150), outline="red", width=6)
    out = io.BytesIO()
    made.save(out, format="PNG")
    return "drawing.png", out.getvalue(), "image/png"


FILES = {"appointment": appointment, "bill": bill, "label": label, "gym_plan": gym_plan, "shapes": shapes}
