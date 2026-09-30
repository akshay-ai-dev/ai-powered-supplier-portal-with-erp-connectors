"""Communication experiment: send one test email to Mailpit."""

import smtplib
from email.message import EmailMessage


def main() -> None:
    msg = EmailMessage()
    msg["From"] = "no-reply@supplier-portal.local"
    msg["To"] = "buyer@demo.local"
    msg["Subject"] = "Test: Response received for REQ-0001"
    msg.set_content(
        "A supplier has responded to REQ-0001.\n\n"
        "Open in portal: http://localhost:5173/requests/REQ-0001"
    )

    # Mailpit on this laptop: port 1025, no login, no TLS
    with smtplib.SMTP("localhost", 1025) as server:
        server.send_message(msg)

    print("Email sent. Check http://localhost:8025")


if __name__ == "__main__":
    main()