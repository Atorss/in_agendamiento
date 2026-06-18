# -*- coding: utf-8 -*-
"""Validador de cédula ecuatoriana.

Algoritmo módulo 10 oficial del Registro Civil del Ecuador.

Reglas:
1. Tiene exactamente 10 dígitos numéricos.
2. Los primeros 2 dígitos representan la provincia: 01 a 24 (válidas), 30
   (exterior) y 50 (otros).
3. El tercer dígito debe ser menor a 6 (personas naturales).
4. Los primeros 9 dígitos pasan por algoritmo módulo 10:
   - Multiplicar posiciones impares (1,3,5,7,9) por 2; si producto > 9, restar 9.
   - Sumar todos los productos.
   - Verificador = (10 - (suma mod 10)) mod 10.
   - Debe coincidir con el dígito 10.
"""

VALID_PROVINCES = set(range(1, 25)) | {30, 50}


def validate_ec_cedula(cedula):
    """Valida una cédula ecuatoriana.

    Returns:
        (bool, str): (es_valida, mensaje_error_si_no_lo_es)
    """
    if not cedula:
        return False, 'Cédula vacía.'

    s = ''.join(c for c in str(cedula).strip() if c.isdigit())
    if len(s) != 10:
        return False, 'La cédula debe tener exactamente 10 dígitos.'

    try:
        provincia = int(s[:2])
    except ValueError:
        return False, 'Cédula con caracteres no numéricos.'
    if provincia not in VALID_PROVINCES:
        return False, f'Provincia inválida ({provincia:02d}).'

    if int(s[2]) >= 6:
        return False, 'Cédula no corresponde a persona natural.'

    coef = [2, 1, 2, 1, 2, 1, 2, 1, 2]
    suma = 0
    for i in range(9):
        prod = int(s[i]) * coef[i]
        if prod > 9:
            prod -= 9
        suma += prod
    digito_verificador = (10 - (suma % 10)) % 10
    if digito_verificador != int(s[9]):
        return False, 'Dígito verificador incorrecto.'

    return True, ''


def extract_cedula(text):
    """Extrae la primera secuencia de 10 dígitos consecutivos de un texto.

    Útil cuando el cliente escribe "Mi cédula es 0102290936" o "0102290936".
    """
    if not text:
        return ''
    import re
    m = re.search(r'\b\d{10}\b', str(text))
    return m.group(0) if m else ''
