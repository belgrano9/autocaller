# e:\workspace\autocaller\scripts\utils.py
"""
Utility functions for text slugification and phone number formatting.
Shared across scraping, email verification, and visual verification modules.
"""

import re
import unicodedata
import phonenumbers

def slugify(value: str) -> str:
    """
    Converts a string into a clean, lowercase, filename-safe slug.
    Normalizes unicode characters (removes accents) and replaces spaces/hyphens with underscores.
    
    Args:
        value: The string to slugify (e.g. "Château de Méridon").
        
    Returns:
        A cleaned, URL-friendly and filename-friendly string (e.g. "chateau_de_meridon").
    """
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('ascii')
    value = re.sub(r'[^\w\s-]', '', value).strip().lower()
    value = re.sub(r'[-\s]+', '_', value)
    return value

def format_phone(phone: str, default_country: str = "FR") -> str:
    """
    Standardizes international and national telephone numbers using Google's libphonenumber.
    Ingests raw phone strings, handles multiple numbers (separated by slashes or commas),
    and formats them to the local national style (e.g. '0X XX XX XX XX' for France)
    if they belong to the default country. Otherwise formats them to the international standard.
    
    Args:
        phone: The raw phone number string to format.
        default_country: The default 2-letter ISO country code (defaults to "FR").
        
    Returns:
        A standardized phone string (e.g. '01 43 86 60 56'), or the original cleaned value
        if validation fails. Multiple numbers are rejoined with " / ".
    """
    if not phone or phone.strip() in ("", "-", "None"):
        return ""
    
    # Split multiple phone numbers if present
    parts = re.split(r'[/,]', phone)
    formatted_parts = []
    
    for part in parts:
        part = part.strip()
        if not part:
            continue
        try:
            # Parse using the default country code
            parsed = phonenumbers.parse(part, default_country.upper())
            if phonenumbers.is_valid_number(parsed):
                region = phonenumbers.region_code_for_number(parsed)
                # If matches default country, use national spacing. Otherwise use international.
                if region == default_country.upper():
                    fmt = phonenumbers.PhoneNumberFormat.NATIONAL
                else:
                    fmt = phonenumbers.PhoneNumberFormat.INTERNATIONAL
                formatted_parts.append(phonenumbers.format_number(parsed, fmt))
            else:
                formatted_parts.append(part)
        except Exception:
            formatted_parts.append(part)
            
    return " / ".join(formatted_parts)
