# -*- coding: utf-8 -*-
"""Conocimiento del negocio para el agente — RAG ligero por palabras clave.

Cada tenant (res.company) carga entradas tema/respuesta. La tool
`buscar_conocimiento` del agente WhatsApp consulta este modelo cuando el
cliente pregunta algo que NO es agendar/cancelar/cobrar (ej. "¿tienen
parqueadero?", "¿aceptan seguro?", "¿formas de pago?").

No es un bot predefinido: el LLM recibe las entradas relevantes como CONTEXTO
y responde con su propio tono. Si no hay coincidencias, lo dice y no inventa
(coherente con global_base + RDCM).

Búsqueda: solapamiento de tokens normalizados (sin acentos, sin stopwords)
entre la consulta y (tema + palabras_clave + respuesta). Sin embeddings: es
suficiente para el volumen de un negocio pequeño y se migra a vectores más
adelante sin tocar el agente.
"""
import unicodedata

from odoo import api, fields, models

# Palabras vacías que no aportan a la búsqueda.
_STOPWORDS = {
    'el', 'la', 'los', 'las', 'un', 'una', 'unos', 'unas', 'de', 'del', 'al',
    'en', 'y', 'o', 'u', 'que', 'cual', 'cuales', 'como', 'para', 'por', 'con',
    'sin', 'su', 'sus', 'mi', 'tu', 'es', 'son', 'hay', 'tiene', 'tienen', 'me',
    'te', 'se', 'lo', 'cuanto', 'cuanta', 'donde', 'cuando', 'quien', 'sobre',
    'si', 'no', 'muy', 'mas', 'esta', 'este', 'estan', 'puedo', 'puede',
}

_MAX_RESULTS = 3
_MIN_TOKEN_LEN = 3


def _normalize(text):
    """Lowercase, sin acentos, signos → espacio. Devuelve string limpio."""
    if not text:
        return ''
    text = unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('ASCII')
    text = text.lower()
    cleaned = ''.join(ch if ch.isalnum() else ' ' for ch in text)
    return ' '.join(cleaned.split())


def _tokens(text):
    """Conjunto de tokens útiles: normalizados, sin stopwords, len >= 3."""
    return {
        t for t in _normalize(text).split()
        if len(t) >= _MIN_TOKEN_LEN and t not in _STOPWORDS
    }


class BusinessKnowledge(models.Model):
    _name = 'innatum.business.knowledge'
    _description = 'Conocimiento del negocio para el agente'
    _order = 'sequence, id'

    company_id = fields.Many2one(
        'res.company', string='Compañía', required=True, index=True,
        default=lambda self: self.env.company,
    )
    name = fields.Char(
        string='Tema / Pregunta', required=True,
        help='Tema o pregunta típica del cliente. Ej: "¿Tienen parqueadero?".',
    )
    answer = fields.Text(
        string='Respuesta', required=True,
        help='Lo que el agente debe saber. No tiene que ser literal: el agente '
             'lo reformula con su propio tono.',
    )
    keywords = fields.Char(
        string='Palabras clave',
        help='Términos extra para que la búsqueda encuentre esta entrada, '
             'separados por coma. Ej: "estacionamiento, carro, auto".',
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    @api.model
    def search_knowledge(self, params, session=None):
        """Tool del agente. params: {'query': str}.

        Devuelve:
          {'total': int, 'resultados': [{'tema', 'respuesta'}]}  con coincidencias
          {'resultados': [], 'message': str}                     sin coincidencias
        """
        query = ''
        if isinstance(params, dict):
            query = params.get('query') or params.get('pregunta') or params.get('q') or ''
        query = (query or '').strip()

        company = (session.company_id if session and session.company_id
                   else self.env.company)

        entries = self.sudo().with_company(company).search([
            ('company_id', '=', company.id),
        ])
        if not entries:
            return {'resultados': [],
                    'message': 'El negocio aún no tiene información cargada.'}

        q_tokens = _tokens(query)
        if not q_tokens:
            return {'resultados': [], 'message': 'No entendí la consulta.'}

        scored = []
        for e in entries:
            haystack = _tokens('%s %s %s' % (
                e.name or '', e.keywords or '', e.answer or ''))
            overlap = len(q_tokens & haystack)
            if overlap:
                scored.append((overlap, e.sequence, e.id, e))

        if not scored:
            return {'resultados': [],
                    'message': 'No encontré información sobre eso en el negocio.'}

        # Más tokens en común primero; empata por sequence y luego id.
        scored.sort(key=lambda t: (-t[0], t[1], t[2]))
        top = scored[:_MAX_RESULTS]
        return {
            'total': len(top),
            'resultados': [{'tema': e.name, 'respuesta': e.answer}
                           for _, _, _, e in top],
        }
