# -*- coding: utf-8 -*-
import json
import logging
from datetime import datetime, timedelta

import pytz

from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

TZ = pytz.timezone('America/Guayaquil')
MAX_TOOL_ITERATIONS = 4

_DIAS = {
    'Monday': 'Lunes', 'Tuesday': 'Martes', 'Wednesday': 'Miércoles',
    'Thursday': 'Jueves', 'Friday': 'Viernes', 'Saturday': 'Sábado', 'Sunday': 'Domingo',
}


def _fecha_es(dt):
    """Formatea datetime a 'Lunes 24/03/2026' en español."""
    dia_en = dt.strftime('%A')
    dia_es = _DIAS.get(dia_en, dia_en)
    return f"{dia_es} {dt.strftime('%d/%m/%Y')}"


class ChatbotEngine(models.AbstractModel):
    _name = 'innatum.ai.chatbot'
    _description = 'Motor de chatbot para agendamiento web'

    # ------------------------------------------------------------------
    # Tool Schemas (formato Anthropic, normalizado internamente por engine)
    # ------------------------------------------------------------------

    def _get_tool_schemas(self):
        return [
            {
                'name': 'listar_servicios',
                'description': (
                    'Lista los servicios con disponibilidad de turnos. '
                    'Usa esta herramienta SIEMPRE que necesites mostrar servicios al cliente, '
                    'ya sea al inicio o cuando quiera cambiar de servicio.'
                ),
                'input_schema': {
                    'type': 'object',
                    'properties': {},
                    'required': [],
                },
            },
            {
                'name': 'listar_profesionales',
                'description': (
                    'Lista los profesionales disponibles para un servicio. '
                    'Usa esta herramienta cuando el cliente pregunte qué profesionales hay '
                    'o quiera saber quién atiende un servicio.'
                ),
                'input_schema': {
                    'type': 'object',
                    'properties': {
                        'servicio': {
                            'type': 'string',
                            'description': 'Código del servicio. Opcional: si no se indica, lista todos.',
                        },
                    },
                    'required': [],
                },
            },
            {
                'name': 'buscar_disponibilidad',
                'description': (
                    'Busca turnos (citas) disponibles. Devuelve lista de horarios libres '
                    'agrupados por profesional y fecha. Usa esta herramienta cuando el '
                    'cliente quiere agendar una cita o pregunta por disponibilidad.'
                ),
                'input_schema': {
                    'type': 'object',
                    'properties': {
                        'servicio': {
                            'type': 'string',
                            'description': 'Código del servicio.',
                        },
                        'profesional_nombre': {
                            'type': 'string',
                            'description': 'Nombre parcial del profesional para filtrar (opcional)',
                        },
                        'fecha': {
                            'type': 'string',
                            'description': 'Fecha específica YYYY-MM-DD (opcional). Si no se indica, busca los próximos 14 días.',
                        },
                    },
                    'required': ['servicio'],
                },
            },
            {
                'name': 'reservar_turno',
                'description': (
                    'Reserva un turno disponible para el cliente ya identificado. '
                    'NO necesitas pedir datos del cliente, ya está identificado. '
                    'ANTES de reservar: confirma los detalles con el cliente.'
                ),
                'input_schema': {
                    'type': 'object',
                    'properties': {
                        'turno_id': {
                            'type': 'integer',
                            'description': 'ID del turno a reservar (obtenido de buscar_disponibilidad)',
                        },
                        'servicio_codigo': {
                            'type': 'string',
                            'description': (
                                'Código del servicio elegido. Solo necesario '
                                'cuando el horario ofrece varios servicios y '
                                'el cliente debe escoger uno.'
                            ),
                        },
                        'motivo': {
                            'type': 'string',
                            'description': 'Motivo de la cita (opcional)',
                        },
                    },
                    'required': ['turno_id'],
                },
            },
            {
                'name': 'cambiar_cliente',
                'description': (
                    'Reinicia la identificación del cliente para que pueda ingresar '
                    'otro número de cédula o identificación. Usa esta herramienta cuando '
                    'el cliente diga que la cédula está mal, que quiere cambiar de persona, '
                    'que quiere ingresar otra identificación, o que el turno es para alguien más.'
                ),
                'input_schema': {
                    'type': 'object',
                    'properties': {},
                    'required': [],
                },
            },
        ]

    # ------------------------------------------------------------------
    # System Prompt Builder
    # ------------------------------------------------------------------

    def _build_system_prompt(self, session=None):
        company = self.env.company
        today = fields.Date.today()

        # Aislamiento multi-tenant: solo los servicios del tenant actual.
        # innatum.agenda.servicio es por tenant (company_id) y aquí va con
        # sudo(), así que NI with_company NI la ir.rule global lo filtran:
        # hay que acotar por company explícitamente o se filtran los
        # servicios de TODOS los tenants al prompt del LLM.
        servicios = self.env['innatum.agenda.servicio'].sudo().search([
            ('company_id', '=', company.id),
        ])
        Turno = self.env['innatum.agenda.turno'].sudo()
        svc_lines = []
        for s in servicios:
            turnos = Turno.search([
                ('servicio_ids', 'in', s.id),
                ('state', '=', 'available'),
                ('publicar', '=', True),
                ('date_start', '>=', fields.Datetime.now()),
                ('company_id', '=', company.id),
            ], limit=1)
            disponible = ' (con disponibilidad)' if turnos else ' (sin disponibilidad actual)'
            svc_lines.append(f"  - {s.name} → código: {s.code}{disponible}")

        servicios_text = '\n'.join(svc_lines) if svc_lines else '  (sin servicios configurados)'

        cliente_info = ''
        if session and session.partner_id:
            partner = session.partner_id
            cliente_info = f"\nCLIENTE IDENTIFICADO: {partner.name}. NO pidas datos personales."

        now = datetime.now(TZ)
        dia_semana = _DIAS.get(now.strftime('%A'), now.strftime('%A'))

        return f"""Eres el asistente virtual para agendar citas de {company.name}.
Hoy es {dia_semana} {today.strftime('%d/%m/%Y')}. Zona horaria: America/Guayaquil.
Cuando el cliente diga "el lunes", "el jueves", etc., calcula la fecha EXACTA a partir de hoy.
{cliente_info}

SERVICIOS CON DISPONIBILIDAD:
{servicios_text}

FLUJO OBLIGATORIO (sigue SIEMPRE este orden):
1. Cuando necesites mostrar servicios → usa SIEMPRE listar_servicios. NUNCA listes de memoria.
2. Cuando el cliente elija servicio → usa listar_profesionales con el código.
   - Si hay UN solo profesional: informa quién es y busca disponibilidad AUTOMÁTICAMENTE.
   - Si hay VARIOS: preséntalos y pregunta con cuál prefiere.
3. Cuando tengas profesional definido → usa buscar_disponibilidad.
4. Cuando el cliente seleccione un horario → reserva INMEDIATAMENTE con reservar_turno. NO preguntes confirmación adicional.
5. Muestra mensaje de despedida tras la reserva.

REGLAS:
- Responde SIEMPRE en español, sé amable y conciso
- NO saltes pasos del flujo
- Si preguntan algo fuera de agenda, responde cortésmente que solo puedes ayudar con turnos y registro de clientes
- Si no hay disponibilidad, sugiere otra fecha, profesional o servicio
- NUNCA inventes horarios, usa SIEMPRE buscar_disponibilidad
- Cuando el cliente seleccione un horario desde las tarjetas, RESERVA INMEDIATAMENTE
- Si el cliente dice que la identificación está mal, que quiere cambiar de persona, que el turno es para alguien más, o cualquier variación de esto → usa cambiar_cliente INMEDIATAMENTE. Responde amablemente que puede ingresar la nueva identificación.

REGLA CRÍTICA - PRESENTACIÓN DE SERVICIOS:
Cuando listar_servicios devuelva resultados, el sistema los muestra AUTOMÁTICAMENTE como botones. Solo responde con una frase corta como: "Estos son los servicios disponibles:"

REGLA CRÍTICA - PRESENTACIÓN DE HORARIOS:
Cuando buscar_disponibilidad devuelva slots, el sistema los muestra AUTOMÁTICAMENTE como tarjetas. Solo responde con una frase corta como: "Encontré N horarios disponibles. Selecciona el que prefieras:"

REGLA CRÍTICA - PRESENTACIÓN DE PROFESIONALES:
Cuando listar_profesionales devuelva resultados:
- Si hay UN solo profesional: NO preguntes. Di "El profesional disponible es [nombre]" y llama buscar_disponibilidad INMEDIATAMENTE.
- Si hay VARIOS: lista sus nombres. Pregunta cuál prefiere."""

    # ------------------------------------------------------------------
    # Tool Executors
    # ------------------------------------------------------------------

    def _execute_tool(self, tool_name, params, session=None):
        dispatch = {
            'listar_servicios': self._tool_listar_servicios,
            'listar_profesionales': self._tool_listar_profesionales,
            'buscar_disponibilidad': self._tool_buscar_disponibilidad,
            'reservar_turno': lambda p: self._tool_reservar_turno(p, session),
            'cambiar_cliente': lambda p: self._tool_cambiar_cliente(p, session),
        }
        handler = dispatch.get(tool_name)
        if not handler:
            return {'error': f'Herramienta no disponible: {tool_name}'}
        try:
            return handler(params)
        except Exception as e:
            _logger.error('Chatbot tool %s error: %s', tool_name, str(e))
            return {'error': str(e)}

    def _tool_listar_servicios(self, params):
        """Lista servicios con turnos disponibles. Delegado a primitives."""
        Primitives = self.env['innatum.agenda.scheduling.primitives']
        return Primitives.list_services(company=self.env.company)

    def _tool_listar_profesionales(self, params):
        """Lista profesionales con turnos disponibles. Delegado a primitives."""
        Primitives = self.env['innatum.agenda.scheduling.primitives']
        return Primitives.list_professionals(
            servicio_code=(params or {}).get('servicio'),
            company=self.env.company,
        )

    def _tool_buscar_disponibilidad(self, params):
        """Busca turnos disponibles. Delegado a primitives."""
        Primitives = self.env['innatum.agenda.scheduling.primitives']
        return Primitives.find_availability(
            servicio_code=(params or {}).get('servicio', ''),
            profesional_nombre=(params or {}).get('profesional_nombre'),
            fecha=(params or {}).get('fecha'),
            company=self.env.company,
        )

    def _tool_reservar_turno(self, params, session=None):
        """Reserva un turno. Delegado a primitives + cliente desde la sesión."""
        if not session or not session.partner_id:
            return {'error': 'No se ha identificado al cliente.'}
        Primitives = self.env['innatum.agenda.scheduling.primitives']
        return Primitives.reserve_existing(
            turno_id=(params or {}).get('turno_id'),
            partner_id=session.partner_id.id,
            servicio_code=(params or {}).get('servicio_codigo'),
            motivo=(params or {}).get('motivo'),
            company=self.env.company,
        )

    def _tool_cambiar_cliente(self, params, session=None):
        """Reinicia la sesión para que el cliente ingrese otra identificación."""
        if session:
            session.write({
                'state': 'pending_id',
                'partner_id': False,
                'register_vat': False,
            })
        return {
            'cambiar_cliente': True,
            'mensaje': 'Sesión reiniciada. Por favor ingresa el número de identificación del cliente.',
        }

    # ------------------------------------------------------------------
    # Main Chat Loop
    # ------------------------------------------------------------------

    @api.model
    def process_message(self, session, user_message):
        """Procesa un mensaje del usuario y retorna dict con texto + datos UI."""
        messages = json.loads(session.api_messages or '[]')
        messages.append({'role': 'user', 'content': user_message})

        provider = session.provider_id
        engine = self.env['innatum.ai.engine'].with_context(
            ai_source='chatbot_web',
            ai_record_ref=f'innatum.ai.chatbot.session,{session.id}',
        )
        caller = engine._get_api_caller(provider)
        system_prompt = self._build_system_prompt(session=session)
        tools = self._get_tool_schemas()

        final_text = ''
        ui_data = {}

        for _iteration in range(MAX_TOOL_ITERATIONS):
            response = caller(provider, messages, tools=tools, system=system_prompt)

            content_blocks = response.get('content', [])
            stop_reason = response.get('stop_reason', 'end_turn')

            text_parts = [b['text'] for b in content_blocks if b.get('type') == 'text']
            tool_uses = [b for b in content_blocks if b.get('type') == 'tool_use']

            if not tool_uses or stop_reason != 'tool_use':
                final_text = '\n'.join(text_parts)
                if ui_data.get('slots'):
                    n = len(ui_data['slots'])
                    final_text = f'Encontré {n} horarios disponibles. Selecciona el que prefieras:'
                elif ui_data.get('especialidades'):
                    final_text = '¿Qué servicio necesitas?'
                elif ui_data.get('professionals'):
                    final_text = 'Estos son los profesionales disponibles:'
                messages.append({'role': 'assistant', 'content': final_text})
                break

            _logger.info('Chatbot: %d tool call(s) en iteración %d', len(tool_uses), _iteration + 1)
            messages.append({'role': 'assistant', 'content': content_blocks})

            tool_results = []
            for tu in tool_uses:
                result = self._execute_tool(tu['name'], tu['input'], session=session)

                if tu['name'] == 'listar_servicios' and isinstance(result, dict):
                    especialidades = result.get('especialidades', [])
                    if especialidades:
                        ui_data['especialidades'] = especialidades

                if tu['name'] == 'listar_profesionales' and isinstance(result, dict):
                    professionals = result.get('professionals', [])
                    if len(professionals) > 1:
                        ui_data['professionals'] = professionals

                if tu['name'] == 'buscar_disponibilidad' and isinstance(result, dict):
                    slots = result.get('slots', [])
                    if slots:
                        ui_data['slots'] = slots
                        ui_data['especialidad'] = result.get('especialidad', '')

                if tu['name'] == 'cambiar_cliente' and isinstance(result, dict) and result.get('cambiar_cliente'):
                    ui_data['cambiar_cliente'] = True

                if tu['name'] == 'reservar_turno' and isinstance(result, dict) and result.get('exito'):
                    ui_data['booking'] = {
                        'referencia': result.get('referencia'),
                        'especialidad': result.get('especialidad'),
                        'professional': result.get('professional'),
                        'fecha': result.get('fecha'),
                        'hora': result.get('hora'),
                        'paciente': result.get('paciente'),
                    }
                    turno = self.env['innatum.agenda.turno'].sudo().search(
                        [('name', '=', result.get('referencia')),
                         ('company_id', '=', self.env.company.id)], limit=1
                    )
                    if turno:
                        session.write({
                            'turno_id': turno.id,
                            'partner_id': turno.partner_id.id,
                            'state': 'done',
                        })

                tool_results.append({
                    'type': 'tool_result',
                    'tool_use_id': tu['id'],
                    'content': json.dumps(result, ensure_ascii=False, default=str),
                })

            messages.append({'role': 'user', 'content': tool_results})
        else:
            final_text = 'Lo siento, no pude completar la operación. ¿Puedes intentar de nuevo?'
            messages.append({'role': 'assistant', 'content': final_text})

        if len(messages) > 50:
            messages = messages[-40:]

        session.write({
            'api_messages': json.dumps(messages, ensure_ascii=False, default=str),
            'message_count': session.message_count + 1,
        })

        return {'text': final_text, 'ui': ui_data}
