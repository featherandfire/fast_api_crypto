"""Email service — sends verification codes via SMTP.
If SMTP is not configured, prints the code to stdout (dev mode).
"""
import asyncio
import random
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import settings

_CODE_TTL_MINUTES = 15


def generate_code() -> str:
    return f"{random.randint(0, 999999):06d}"


def code_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=_CODE_TTL_MINUTES)


def _send_sync(to_email: str, code: str) -> None:
    sender = settings.smtp_from or settings.smtp_user
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"{code} is your CryptoFolio verification code"
    msg["From"] = sender
    msg["To"] = to_email

    html = f"""
<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#07050f;font-family:Inter,system-ui,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr><td align="center" style="padding:48px 16px">
      <table width="480" cellpadding="0" cellspacing="0"
             style="background:#0d0a1e;border:1px solid #261d4a;border-radius:12px;overflow:hidden">
        <!-- header -->
        <tr>
          <td style="padding:32px 40px 24px;border-bottom:1px solid #261d4a">
            <div style="font-size:22px;font-weight:700;color:#b44dff;
                        text-shadow:0 0 16px rgba(180,77,255,.6)">
              ₿ CryptoFolio
            </div>
          </td>
        </tr>
        <!-- body -->
        <tr>
          <td style="padding:36px 40px">
            <p style="color:#e8e0ff;font-size:15px;margin:0 0 24px">
              Your verification code is:
            </p>
            <div style="text-align:center;margin:0 0 28px">
              <span style="display:inline-block;padding:18px 40px;
                           background:#14102a;border:1px solid #b44dff;
                           border-radius:8px;font-size:36px;font-weight:700;
                           letter-spacing:12px;color:#b44dff;
                           font-family:'Courier New',monospace;
                           box-shadow:0 0 24px rgba(180,77,255,.3)">
                {code}
              </span>
            </div>
            <p style="color:#5c5280;font-size:13px;margin:0">
              This code expires in {_CODE_TTL_MINUTES} minutes.
              If you didn't create a CryptoFolio account, you can safely ignore this email.
            </p>
          </td>
        </tr>
        <!-- footer -->
        <tr>
          <td style="padding:20px 40px;border-top:1px solid #261d4a">
            <p style="color:#5c5280;font-size:11px;margin:0">
              CryptoFolio &mdash; Crypto Portfolio Tracker
            </p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.sendmail(sender, to_email, msg.as_string())


async def send_verification_code(to_email: str, code: str) -> None:
    """Send the code. Falls back to console log if SMTP not configured."""
    if not settings.smtp_host:
        print(f"\n[DEV] Verification code for {to_email}: {code}\n", flush=True)
        return
    await asyncio.to_thread(_send_sync, to_email, code)
