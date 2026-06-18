# -*- coding: utf-8 -*-
import json
import logging

import requests

from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 5


class AIEngine(models.AbstractModel):
    _name = 'innatum.ai.engine'
    _description = 'Motor de IA'

    # -------------------------------------------------------------------------
    # Disponibilidad pública (gate UI)
    # -------------------------------------------------------------------------

    @api.model
    def _is_chatbot_available_for_company(self, company):
        """Indica si las features de IA están disponibles para una company.

        Default: True (siempre disponible). Otros módulos pueden override
        para agregar lógica de saldo/suscripción (ej. innatum_agenda_planes
        override este método para retornar False si la company no tiene
        recargas IA con saldo).

        Usado por el template del chatbot widget para decidir si se
        renderiza el ícono flotante en el sitio público. Mejor UX que
        mostrarlo y fallar al usarlo.
        """
        return True

    # -------------------------------------------------------------------------
    # Helpers de seguridad y costo
    # -------------------------------------------------------------------------

    def _sanitize_error(self, text, provider):
        """Redacta API key y trunca un mensaje de error antes de exponerlo."""
        if not text:
            return ''
        clean = str(text)[:300]
        api_key = getattr(provider, 'api_key', None)
        if api_key and len(api_key) > 4:
            clean = clean.replace(api_key, '***REDACTED***')
        return clean

    def _log_api_usage(self, provider, usage_dict):
        """Registra una llamada a la API en innatum.ai.usage.log.

        El diccionario `usage_dict` puede venir en varios formatos:
         - Anthropic: {'input_tokens': X, 'output_tokens': Y}
         - OpenAI: {'prompt_tokens': X, 'completion_tokens': Y}
         - Google: {'promptTokenCount': X, 'candidatesTokenCount': Y}

        Si ambos son 0, no se crea log.
        El `source` se obtiene del contexto (`ai_source`), default 'unknown'.
        """
        u = usage_dict or {}
        input_tokens = (
            u.get('input_tokens')
            or u.get('prompt_tokens')
            or u.get('promptTokenCount')
            or 0
        )
        output_tokens = (
            u.get('output_tokens')
            or u.get('completion_tokens')
            or u.get('candidatesTokenCount')
            or 0
        )
        if not (input_tokens or output_tokens):
            return None
        price_in = provider.price_1m_input_usd or 0.0
        price_out = provider.price_1m_output_usd or 0.0
        cost_usd = (
            (input_tokens * price_in + output_tokens * price_out) / 1_000_000
        )
        return self.env['innatum.ai.usage.log'].sudo().create({
            'provider_id': provider.id,
            'model': provider.effective_model,
            'user_id': self.env.user.id,
            'source': self.env.context.get('ai_source') or 'unknown',
            'record_ref': self.env.context.get('ai_record_ref') or False,
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'price_1m_input_snapshot': price_in,
            'price_1m_output_snapshot': price_out,
            'cost_usd': cost_usd,
        })

    def _get_cost_config(self):
        """Lee la configuración de límites desde ir.config_parameter."""
        ICP = self.env['ir.config_parameter'].sudo()
        try:
            monthly_limit = float(ICP.get_param('innatum_ai.monthly_limit_usd', '5.0'))
        except (ValueError, TypeError):
            monthly_limit = 5.0
        try:
            conv_limit = float(ICP.get_param('innatum_ai.max_cost_per_conversation_usd', '0.1'))
        except (ValueError, TypeError):
            conv_limit = 0.1
        action = ICP.get_param('innatum_ai.limit_action', 'block')
        return {
            'monthly_limit': monthly_limit,
            'conv_limit': conv_limit,
            'action': action,
        }

    def _current_month_ai_cost(self):
        """Suma el costo (USD) de todas las llamadas del mes actual en la instancia."""
        from datetime import datetime
        month_start = fields.Date.today().replace(day=1)
        logs = self.env['innatum.ai.usage.log'].sudo().search([
            ('create_date', '>=', fields.Datetime.to_string(
                datetime.combine(month_start, datetime.min.time())
            )),
        ])
        return sum(logs.mapped('cost_usd'))

    def _check_cost_limits(self, provider, conversation=None):
        """Verifica límites ANTES de una llamada a la API.

        Raises UserError si el límite se alcanzó y la acción es 'block'.
        """
        cfg = self._get_cost_config()

        if conversation and cfg['conv_limit'] > 0:
            conv_cost = sum(conversation.message_ids.mapped('cost_usd'))
            if conv_cost >= cfg['conv_limit']:
                msg = (
                    f"Esta conversación alcanzó el límite de costo "
                    f"(${conv_cost:.4f} / ${cfg['conv_limit']:.2f}). "
                    f"Inicia una nueva conversación para continuar."
                )
                _logger.warning("AI cost cap (conversation): %s", msg)
                if cfg['action'] == 'block':
                    raise UserError(msg)

        if cfg['monthly_limit'] > 0:
            month_cost = self._current_month_ai_cost()
            if month_cost >= cfg['monthly_limit']:
                msg = (
                    f"Se alcanzó el límite mensual de IA de la instancia "
                    f"(${month_cost:.4f} / ${cfg['monthly_limit']:.2f}). "
                    f"Contacta al administrador."
                )
                _logger.warning("AI cost cap (monthly): %s", msg)
                if cfg['action'] == 'block':
                    raise UserError(msg)

    # -------------------------------------------------------------------------
    # API Calls per provider
    # -------------------------------------------------------------------------

    def _call_anthropic(self, provider, messages, tools=None, system=None):
        """Llama a la API de Anthropic (Claude)."""
        url = provider.api_base_url or 'https://api.anthropic.com/v1/messages'
        headers = {
            'x-api-key': provider.api_key,
            'anthropic-version': '2023-06-01',
            'content-type': 'application/json',
        }
        payload = {
            'model': provider.effective_model,
            'max_tokens': provider.max_tokens,
            'temperature': provider.temperature,
            'messages': messages,
        }
        if system:
            payload['system'] = system
        if tools:
            payload['tools'] = tools

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=120)
        except requests.Timeout:
            _logger.warning("Anthropic API timeout (120s)")
            raise UserError('La solicitud a Anthropic excedió el tiempo de espera.')
        except requests.ConnectionError as exc:
            _logger.warning("Anthropic API connection error: %s", exc)
            raise UserError('No se pudo conectar con Anthropic.')
        if response.status_code != 200:
            detail = self._sanitize_error(response.text, provider)
            _logger.warning("Anthropic API error %s: %s", response.status_code, detail)
            raise UserError(f'Error de Anthropic ({response.status_code}): {detail}')
        data = response.json()
        try:
            self._log_api_usage(provider, data.get('usage', {}))
        except Exception:
            _logger.exception("Error registrando uso de IA (anthropic)")
        return data

    def _convert_messages_for_openai(self, messages):
        """Convierte mensajes del formato interno (Anthropic) al formato OpenAI."""
        openai_messages = []
        for msg in messages:
            role = msg.get('role', 'user')
            content = msg.get('content', '')

            # Simple text message
            if isinstance(content, str):
                openai_messages.append({'role': role, 'content': content})
                continue

            # Content is a list of blocks (Anthropic format)
            if isinstance(content, list):
                text_parts = []
                tool_calls = []
                tool_results = []

                for block in content:
                    block_type = block.get('type', '')
                    if block_type == 'text':
                        text_parts.append(block.get('text', ''))
                    elif block_type == 'tool_use':
                        tool_calls.append({
                            'id': block['id'],
                            'type': 'function',
                            'function': {
                                'name': block['name'],
                                'arguments': json.dumps(block.get('input', {})),
                            }
                        })
                    elif block_type == 'tool_result':
                        tool_results.append(block)

                # Assistant message with tool calls
                if tool_calls:
                    assistant_msg = {'role': 'assistant'}
                    if text_parts:
                        assistant_msg['content'] = '\n'.join(text_parts)
                    else:
                        assistant_msg['content'] = None
                    assistant_msg['tool_calls'] = tool_calls
                    openai_messages.append(assistant_msg)

                # Tool result messages (each one is a separate message in OpenAI)
                elif tool_results:
                    for tr in tool_results:
                        openai_messages.append({
                            'role': 'tool',
                            'tool_call_id': tr.get('tool_use_id', ''),
                            'content': tr.get('content', ''),
                        })

                # Plain text blocks
                elif text_parts:
                    openai_messages.append({'role': role, 'content': '\n'.join(text_parts)})

        return openai_messages

    def _call_openai(self, provider, messages, tools=None, system=None):
        """Llama a la API de OpenAI."""
        url = provider.api_base_url or 'https://api.openai.com/v1/chat/completions'
        headers = {
            'Authorization': f'Bearer {provider.api_key}',
            'Content-Type': 'application/json',
        }

        # Convert messages from internal (Anthropic) format to OpenAI format
        api_messages = []
        if system:
            api_messages.append({'role': 'system', 'content': system})
        api_messages.extend(self._convert_messages_for_openai(messages))

        payload = {
            'model': provider.effective_model,
            'max_tokens': provider.max_tokens,
            'temperature': provider.temperature,
            'messages': api_messages,
        }

        if tools:
            # Convert from Anthropic tool format to OpenAI format
            openai_tools = []
            for tool in tools:
                openai_tools.append({
                    'type': 'function',
                    'function': {
                        'name': tool['name'],
                        'description': tool.get('description', ''),
                        'parameters': tool.get('input_schema', {}),
                    }
                })
            payload['tools'] = openai_tools

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=120)
        except requests.Timeout:
            _logger.warning("OpenAI API timeout (120s)")
            raise UserError('La solicitud a OpenAI excedió el tiempo de espera.')
        except requests.ConnectionError as exc:
            _logger.warning("OpenAI API connection error: %s", exc)
            raise UserError('No se pudo conectar con OpenAI.')
        if response.status_code != 200:
            detail = self._sanitize_error(response.text, provider)
            _logger.warning("OpenAI API error %s: %s", response.status_code, detail)
            raise UserError(f'Error de OpenAI ({response.status_code}): {detail}')
        normalized = self._normalize_openai_response(response.json())
        try:
            self._log_api_usage(provider, normalized.get('usage', {}))
        except Exception:
            _logger.exception("Error registrando uso de IA (openai)")
        return normalized

    def _call_google(self, provider, messages, tools=None, system=None):
        """Llama a la API de Google Gemini."""
        base_url = provider.api_base_url or 'https://generativelanguage.googleapis.com/v1beta'
        url = f'{base_url}/models/{provider.effective_model}:generateContent?key={provider.api_key}'
        headers = {'Content-Type': 'application/json'}

        # Convert messages to Gemini format
        contents = []
        for msg in messages:
            role = 'model' if msg['role'] == 'assistant' else 'user'
            contents.append({
                'role': role,
                'parts': [{'text': msg['content']}],
            })

        payload = {
            'contents': contents,
            'generationConfig': {
                'maxOutputTokens': provider.max_tokens,
                'temperature': provider.temperature,
            },
        }

        if system:
            payload['systemInstruction'] = {'parts': [{'text': system}]}

        if tools:
            gemini_tools = []
            for tool in tools:
                gemini_tools.append({
                    'name': tool['name'],
                    'description': tool.get('description', ''),
                    'parameters': tool.get('input_schema', {}),
                })
            payload['tools'] = [{'functionDeclarations': gemini_tools}]

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=120)
        except requests.Timeout:
            _logger.warning("Google Gemini API timeout (120s)")
            raise UserError('La solicitud a Google Gemini excedió el tiempo de espera.')
        except requests.ConnectionError as exc:
            _logger.warning("Google Gemini API connection error: %s", exc)
            raise UserError('No se pudo conectar con Google Gemini.')
        if response.status_code != 200:
            detail = self._sanitize_error(response.text, provider)
            _logger.warning("Google Gemini API error %s: %s", response.status_code, detail)
            raise UserError(f'Error de Google ({response.status_code}): {detail}')
        normalized = self._normalize_google_response(response.json())
        try:
            self._log_api_usage(provider, normalized.get('usage', {}))
        except Exception:
            _logger.exception("Error registrando uso de IA (google)")
        return normalized

    # -------------------------------------------------------------------------
    # Response normalizers (convert to Anthropic format internally)
    # -------------------------------------------------------------------------

    def _normalize_openai_response(self, response):
        """Convierte respuesta OpenAI al formato interno (Anthropic-like)."""
        choice = response.get('choices', [{}])[0]
        message = choice.get('message', {})

        content = []
        if message.get('content'):
            content.append({'type': 'text', 'text': message['content']})

        if message.get('tool_calls'):
            for tc in message['tool_calls']:
                content.append({
                    'type': 'tool_use',
                    'id': tc['id'],
                    'name': tc['function']['name'],
                    'input': json.loads(tc['function'].get('arguments', '{}')),
                })

        stop_reason = 'tool_use' if message.get('tool_calls') else 'end_turn'

        return {
            'content': content,
            'stop_reason': stop_reason,
            'usage': response.get('usage', {}),
        }

    def _normalize_google_response(self, response):
        """Convierte respuesta Google Gemini al formato interno."""
        candidates = response.get('candidates', [{}])
        if not candidates:
            return {'content': [{'type': 'text', 'text': 'Sin respuesta del modelo.'}], 'stop_reason': 'end_turn'}

        parts = candidates[0].get('content', {}).get('parts', [])
        content = []

        for part in parts:
            if 'text' in part:
                content.append({'type': 'text', 'text': part['text']})
            elif 'functionCall' in part:
                fc = part['functionCall']
                content.append({
                    'type': 'tool_use',
                    'id': f"google_{fc['name']}",
                    'name': fc['name'],
                    'input': fc.get('args', {}),
                })

        has_tool_use = any(c['type'] == 'tool_use' for c in content)

        # Normalize Google usage metadata
        usage_meta = response.get('usageMetadata', {})
        usage = {
            'input_tokens': usage_meta.get('promptTokenCount', 0),
            'output_tokens': usage_meta.get('candidatesTokenCount', 0),
        }

        return {
            'content': content,
            'stop_reason': 'tool_use' if has_tool_use else 'end_turn',
            'usage': usage,
        }

    def _extract_usage(self, response, provider_type):
        """Extrae tokens de uso normalizados de la respuesta API."""
        usage = response.get('usage', {})
        if provider_type == 'anthropic':
            return {
                'input_tokens': usage.get('input_tokens', 0),
                'output_tokens': usage.get('output_tokens', 0),
            }
        elif provider_type == 'openai':
            return {
                'input_tokens': usage.get('prompt_tokens', 0),
                'output_tokens': usage.get('completion_tokens', 0),
            }
        # Google already normalized in _normalize_google_response
        return {
            'input_tokens': usage.get('input_tokens', 0),
            'output_tokens': usage.get('output_tokens', 0),
        }

    # -------------------------------------------------------------------------
    # Main engine
    # -------------------------------------------------------------------------

    def _get_api_caller(self, provider):
        """Retorna la función de llamada API según el proveedor."""
        callers = {
            'anthropic': self._call_anthropic,
            'openai': self._call_openai,
            'google': self._call_google,
        }
        caller = callers.get(provider.provider_type)
        if not caller:
            raise UserError(f'Proveedor no soportado: {provider.provider_type}')
        return caller

    def _get_active_tools(self):
        """Obtiene las herramientas activas y genera sus schemas."""
        tools = self.env['innatum.ai.tool'].search([('active', '=', True)])
        user = self.env.user
        schemas = []
        available_tools = {}
        for tool in tools:
            if tool.check_tool_access(user):
                schema = tool._get_tool_schema()
                schemas.append(schema)
                available_tools[tool.name] = tool
        return schemas, available_tools

    def _build_context_prompt(self, provider):
        """Construye el prompt del sistema con contexto del ERP."""
        base_prompt = provider.system_prompt or ''

        # Get compact data dictionary (alias → model only, no fields)
        data_dict = self.env['innatum.ai.data.dict'].get_context_for_ai()

        context = (
            f"\nERP Odoo. Usuario: {self.env.user.name}. "
            f"Empresa: {self.env.company.name}. Fecha: {fields.Date.today()}.\n"
        )

        if data_dict:
            context += f"\n{data_dict}\n"

        context += (
            "\nREGLAS:\n"
            "1. Usa el diccionario para identificar el modelo correcto. NO adivines modelos.\n"
            "2. Para contar registros usa search_records con limit=1 y lee el total del resultado.\n"
            "3. Usa list_model_fields SOLO si necesitas saber qué campos filtrar o leer.\n"
            "4. Prefiere search_records sobre sql_report.\n"
            "5. Mínimas llamadas posibles (ideal: 1-2).\n"
        )

        return base_prompt + context

    @api.model
    def simple_completion(self, provider, prompt):
        """Hace una llamada simple sin herramientas (para test de conexión)."""
        self._check_cost_limits(provider)
        caller = self._get_api_caller(provider)
        messages = [{'role': 'user', 'content': prompt}]
        response = caller(provider, messages)

        for block in response.get('content', []):
            if block.get('type') == 'text':
                return block['text']
        return 'Sin respuesta de texto.'

    @api.model
    def vision_completion(self, provider, prompt, images, system=None, temperature=None):
        """
        Envía imágenes + texto al modelo de IA con soporte de visión.
        :param provider: innatum.ai.provider record
        :param prompt: texto del prompt
        :param images: lista de dicts {'data': base64_str, 'media_type': 'image/jpeg'}
        :param system: prompt de sistema opcional
        :param temperature: temperatura override (None usa la del proveedor)
        :return: texto de respuesta
        """
        self._check_cost_limits(provider)
        temp = temperature if temperature is not None else provider.temperature
        model = provider.effective_model

        if provider.provider_type == 'anthropic':
            content = []
            for img in images:
                content.append({
                    'type': 'image',
                    'source': {
                        'type': 'base64',
                        'media_type': img['media_type'],
                        'data': img['data'],
                    },
                })
            content.append({'type': 'text', 'text': prompt})

            url = provider.api_base_url or 'https://api.anthropic.com/v1/messages'
            headers = {
                'x-api-key': provider.api_key,
                'anthropic-version': '2023-06-01',
                'content-type': 'application/json',
            }
            payload = {
                'model': model,
                'max_tokens': provider.max_tokens,
                'temperature': temp,
                'messages': [{'role': 'user', 'content': content}],
            }
            if system:
                payload['system'] = system

            resp = requests.post(url, headers=headers, json=payload, timeout=180)
            if resp.status_code != 200:
                detail = self._sanitize_error(resp.text, provider)
                raise UserError(f'Error de Anthropic Vision ({resp.status_code}): {detail}')
            data = resp.json()
            try:
                self._log_api_usage(provider, data.get('usage', {}))
            except Exception:
                _logger.exception("Error registrando uso de IA (vision anthropic)")
            for block in data.get('content', []):
                if block.get('type') == 'text':
                    return block['text']

        elif provider.provider_type == 'openai':
            content = []
            for img in images:
                content.append({
                    'type': 'image_url',
                    'image_url': {
                        'url': f"data:{img['media_type']};base64,{img['data']}",
                        'detail': 'high',
                    },
                })
            content.append({'type': 'text', 'text': prompt})

            url = provider.api_base_url or 'https://api.openai.com/v1/chat/completions'
            headers = {
                'Authorization': f'Bearer {provider.api_key}',
                'Content-Type': 'application/json',
            }
            messages = []
            if system:
                messages.append({'role': 'system', 'content': system})
            messages.append({'role': 'user', 'content': content})

            payload = {
                'model': model,
                'max_tokens': provider.max_tokens,
                'temperature': temp,
                'messages': messages,
            }

            resp = requests.post(url, headers=headers, json=payload, timeout=180)
            if resp.status_code != 200:
                detail = self._sanitize_error(resp.text, provider)
                raise UserError(f'Error de OpenAI Vision ({resp.status_code}): {detail}')
            data = resp.json()
            openai_usage = data.get('usage', {}) or {}
            try:
                self._log_api_usage(provider, {
                    'input_tokens': openai_usage.get('prompt_tokens', 0),
                    'output_tokens': openai_usage.get('completion_tokens', 0),
                })
            except Exception:
                _logger.exception("Error registrando uso de IA (vision openai)")
            choice = data.get('choices', [{}])[0]
            text = choice.get('message', {}).get('content', '')
            if text:
                return text

        elif provider.provider_type == 'google':
            parts = []
            for img in images:
                parts.append({
                    'inlineData': {
                        'mimeType': img['media_type'],
                        'data': img['data'],
                    },
                })
            parts.append({'text': prompt})

            base_url = provider.api_base_url or 'https://generativelanguage.googleapis.com/v1beta'
            url = f'{base_url}/models/{model}:generateContent?key={provider.api_key}'
            headers = {'Content-Type': 'application/json'}
            payload = {
                'contents': [{'role': 'user', 'parts': parts}],
                'generationConfig': {
                    'maxOutputTokens': provider.max_tokens,
                    'temperature': temp,
                },
            }
            if system:
                payload['systemInstruction'] = {'parts': [{'text': system}]}

            resp = requests.post(url, headers=headers, json=payload, timeout=180)
            if resp.status_code != 200:
                detail = self._sanitize_error(resp.text, provider)
                raise UserError(f'Error de Google Vision ({resp.status_code}): {detail}')
            data = resp.json()
            gm_usage = data.get('usageMetadata', {}) or {}
            try:
                self._log_api_usage(provider, {
                    'input_tokens': gm_usage.get('promptTokenCount', 0),
                    'output_tokens': gm_usage.get('candidatesTokenCount', 0),
                })
            except Exception:
                _logger.exception("Error registrando uso de IA (vision google)")
            candidates = data.get('candidates', [])
            if candidates:
                for part in candidates[0].get('content', {}).get('parts', []):
                    if 'text' in part:
                        return part['text']
        else:
            raise UserError(f'Proveedor no soportado para visión: {provider.provider_type}')

        return 'Sin respuesta de texto.'

    @api.model
    def chat(self, provider, conversation, user_message):
        """
        Procesa un mensaje del usuario con soporte de tool use.
        Loop: envía mensaje → si la IA pide tools → ejecuta → envía resultados → repite.
        """
        self._check_cost_limits(provider, conversation)

        # Save user message
        conversation.add_message('user', user_message)

        # Get tools and system prompt
        tool_schemas, available_tools = self._get_active_tools()
        system_prompt = self._build_context_prompt(provider)

        # Build messages history
        messages = conversation.get_messages_for_api()

        caller = self._get_api_caller(provider)

        iterations = 0
        final_text = ''

        while iterations < MAX_TOOL_ITERATIONS:
            iterations += 1

            # En cada iteración revisar límites (tool loops pueden acumular costo)
            self._check_cost_limits(provider, conversation)

            # Call the API
            response = caller(
                provider, messages,
                tools=tool_schemas if tool_schemas else None,
                system=system_prompt,
            )

            content_blocks = response.get('content', [])
            stop_reason = response.get('stop_reason', 'end_turn')

            # Extract token usage
            usage = self._extract_usage(response, provider.provider_type)
            input_tk = usage.get('input_tokens', 0)
            output_tk = usage.get('output_tokens', 0)

            # Extract text parts
            text_parts = []
            tool_use_blocks = []

            for block in content_blocks:
                if block.get('type') == 'text':
                    text_parts.append(block['text'])
                elif block.get('type') == 'tool_use':
                    tool_use_blocks.append(block)

            current_text = '\n'.join(text_parts)

            if not tool_use_blocks or stop_reason != 'tool_use':
                # No tool calls - we're done
                final_text = current_text
                conversation.add_message('assistant', final_text,
                                         input_tokens=input_tk, output_tokens=output_tk)
                break

            # Process tool calls
            _logger.info('AI requesting %d tool call(s), tokens: in=%d out=%d',
                         len(tool_use_blocks), input_tk, output_tk)

            # Save assistant message with tool requests and token usage
            conversation.add_message(
                'assistant', current_text or '(ejecutando herramientas...)',
                tool_calls=[{
                    'id': tb['id'],
                    'name': tb['name'],
                    'input': tb['input'],
                } for tb in tool_use_blocks],
                input_tokens=input_tk, output_tokens=output_tk,
            )

            # Add assistant message to API conversation
            messages.append({'role': 'assistant', 'content': content_blocks})

            # Execute each tool and collect results
            tool_results_content = []
            all_tool_results = []

            for tb in tool_use_blocks:
                tool_name = tb['name']
                tool_input = tb['input']
                tool_id = tb['id']

                tool = available_tools.get(tool_name)
                if not tool:
                    result = {'error': f'Herramienta no encontrada: {tool_name}'}
                else:
                    _logger.info('Executing tool: %s with params: %s', tool_name, json.dumps(tool_input)[:200])
                    try:
                        with self.env.cr.savepoint():
                            result = tool.execute_tool(tool_input, user=self.env.user)

                            # Handle SQL report requests specially
                            if isinstance(result, dict) and result.get('type') == 'sql_report_request':
                                result = self._handle_sql_report(provider, result['description'])
                    except Exception as e:
                        _logger.error('Tool %s failed: %s', tool_name, str(e))
                        result = {'error': str(e)}

                result_str = json.dumps(result, ensure_ascii=False, default=str)

                tool_results_content.append({
                    'type': 'tool_result',
                    'tool_use_id': tool_id,
                    'content': result_str,
                })

                all_tool_results.append({
                    'tool': tool_name,
                    'result': result,
                })

            # Save tool results
            conversation.add_message(
                'tool_result', json.dumps(all_tool_results, ensure_ascii=False, default=str),
                tool_results=all_tool_results,
            )

            # Add tool results to messages for next API call
            messages.append({'role': 'user', 'content': tool_results_content})

        if iterations >= MAX_TOOL_ITERATIONS:
            final_text += '\n\n⚠️ Se alcanzó el límite de iteraciones de herramientas.'

        return final_text

    def _handle_sql_report(self, provider, description):
        """Genera y ejecuta una consulta SQL de solo lectura."""
        # Get available tables
        self.env.cr.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """)
        tables = [r[0] for r in self.env.cr.fetchall()]

        # Ask the AI to generate the SQL
        sql_prompt = (
            f"Genera SOLO una consulta SQL SELECT (solo lectura) para PostgreSQL que responda a: {description}\n\n"
            f"Tablas disponibles (las más relevantes): {', '.join(tables[:100])}\n\n"
            "REGLAS:\n"
            "- SOLO SELECT, nunca INSERT/UPDATE/DELETE/DROP/ALTER\n"
            "- Limitar a 50 registros máximo\n"
            "- Responde SOLO con el SQL, sin explicaciones ni markdown\n"
        )

        caller = self._get_api_caller(provider)
        response = caller(provider, [{'role': 'user', 'content': sql_prompt}])

        sql = ''
        for block in response.get('content', []):
            if block.get('type') == 'text':
                sql = block['text'].strip()
                break

        # Clean markdown code blocks if present
        if sql.startswith('```'):
            sql = '\n'.join(sql.split('\n')[1:])
        if sql.endswith('```'):
            sql = sql[:-3].strip()

        # Security check
        sql_upper = sql.upper()
        forbidden = ['INSERT', 'UPDATE', 'DELETE', 'DROP', 'ALTER', 'TRUNCATE', 'CREATE', 'GRANT', 'REVOKE']
        for word in forbidden:
            # Check for standalone keywords (not as part of column names)
            if f' {word} ' in f' {sql_upper} ' or sql_upper.startswith(f'{word} '):
                return {'error': f'Consulta rechazada: contiene operación no permitida ({word})'}

        if not sql_upper.lstrip().startswith('SELECT'):
            return {'error': 'Solo se permiten consultas SELECT'}

        try:
            with self.env.cr.savepoint():
                self.env.cr.execute(sql)
                columns = [desc[0] for desc in self.env.cr.description] if self.env.cr.description else []
                rows = self.env.cr.fetchall()

                results = []
                for row in rows[:50]:
                    results.append(dict(zip(columns, [
                        v.isoformat() if hasattr(v, 'isoformat') else v
                        for v in row
                    ])))

                return {
                    'sql': sql,
                    'columns': columns,
                    'row_count': len(results),
                    'results': results,
                }
        except Exception as e:
            return {'error': f'Error ejecutando SQL: {str(e)}', 'sql': sql}
