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


settings = Settings()
