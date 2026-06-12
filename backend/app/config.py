from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_mode: str = "dev"          # "dev" | "int"

    # dev — personal Gmail
    gmail_user: str = ""
    gmail_app_password: str = ""

    # int — Brevo SMTP
    brevo_smtp_user: str = ""      # your Brevo account email
    brevo_smtp_password: str = ""  # xsmtpsib-... key

    from_email: str = ""
    from_name: str = "Devis Mariages"
    reply_to_domain: str = ""
    test_email: str = ""
    webhook_signing_key: str = ""

    # Conciergerie inbound (Brevo inbound parsing). Brevo does not HMAC-sign its
    # inbound webhook, so we authenticate it with an unguessable secret embedded
    # in the configured webhook URL (?secret=...) plus the routing-token lookup.
    inbound_webhook_secret: str = ""

    gemini_api_key: str = ""

    # Supervisor account — can always log in, auto-provisioned if missing
    supervisor_email: str = ""
    supervisor_password: str = ""

    # Stripe — subscription billing (test mode keys; never committed)
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_plus: str = ""          # recurring monthly Price ID — Plus tier
    stripe_price_conciergerie: str = ""  # recurring monthly Price ID — Conciergerie tier
    app_base_url: str = "http://localhost:8000"  # success/cancel/portal-return URLs


settings = Settings()
