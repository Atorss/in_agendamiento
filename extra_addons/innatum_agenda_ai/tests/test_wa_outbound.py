# -*- coding: utf-8 -*-
from unittest.mock import Mock, patch

from odoo.tests.common import TransactionCase


class TestWaOutboundBase(TransactionCase):
    """Base común: compañía-tenant con phone_number_id configurado."""

    def setUp(self):
        super().setUp()
        self.Outbound = self.env['innatum.wa.outbound']
        self.company = self.env['res.company'].create({
            'name': 'Clínica Outbound',
            'wa_phone_number_id': '111222333444',
        })


class TestNormalizacionNumero(TestWaOutboundBase):
    """Normalización de celulares ecuatorianos al formato Meta."""

    def test_formato_local(self):
        self.assertEqual(
            self.Outbound.normalize_ec_number('0996706629'), '593996706629')

    def test_formato_meta_ya_normalizado(self):
        self.assertEqual(
            self.Outbound.normalize_ec_number('593996706629'), '593996706629')

    def test_formato_internacional_con_espacios(self):
        self.assertEqual(
            self.Outbound.normalize_ec_number('+593 99 670 6629'),
            '593996706629')

    def test_formato_sin_cero_inicial(self):
        self.assertEqual(
            self.Outbound.normalize_ec_number('996706629'), '593996706629')

    def test_invalidos_devuelven_false(self):
        for raw in (False, '', 'abc', '02345678', '12345', '59322345678'):
            self.assertFalse(self.Outbound.normalize_ec_number(raw),
                             'Debió rechazar %r' % (raw,))


class TestCreacionCola(TestWaOutboundBase):

    def test_defaults(self):
        rec = self.Outbound.create({
            'company_id': self.company.id,
            'to_number': '593996706629',
            'meta_payload': {'messaging_product': 'whatsapp'},
        })
        self.assertEqual(rec.state, 'pending')
        self.assertEqual(rec.attempts, 0)
        self.assertEqual(rec.category, 'prueba')


class TestQueueTemplate(TestWaOutboundBase):

    def test_encola_plantilla_con_payload_meta(self):
        rec = self.Outbound.queue_template(
            self.company, '0996706629', 'derivacion_colaborador',
            ['Dra. Ana', 'Dr. Baratau', 'Juan Pérez', 'Endodoncia'],
            category='derivacion_colaborador')
        self.assertEqual(rec.state, 'pending')
        self.assertEqual(rec.to_number, '593996706629')
        self.assertEqual(rec.category, 'derivacion_colaborador')
        payload = rec.meta_payload
        self.assertEqual(payload['messaging_product'], 'whatsapp')
        self.assertEqual(payload['to'], '593996706629')
        self.assertEqual(payload['type'], 'template')
        self.assertEqual(payload['template']['name'], 'derivacion_colaborador')
        self.assertEqual(payload['template']['language']['code'], 'es')
        params = payload['template']['components'][0]['parameters']
        self.assertEqual(
            [p['text'] for p in params],
            ['Dra. Ana', 'Dr. Baratau', 'Juan Pérez', 'Endodoncia'])
        self.assertTrue(all(p['type'] == 'text' for p in params))

    def test_botones_quick_reply_en_payload(self):
        rec = self.Outbound.queue_template(
            self.company, '0996706629', 'derivacion_paciente',
            ['Juan Pérez', 'Dr. Baratau', 'Dra. Ana', 'Endodoncia'],
            category='derivacion_paciente',
            buttons=['dp_deriv:7', 'dp_menu:back'])
        comps = rec.meta_payload['template']['components']
        self.assertEqual([c['type'] for c in comps],
                         ['body', 'button', 'button'])
        for idx, payload in enumerate(['dp_deriv:7', 'dp_menu:back']):
            btn = comps[1 + idx]
            self.assertEqual(btn['sub_type'], 'quick_reply')
            self.assertEqual(btn['index'], str(idx))
            self.assertEqual(btn['parameters'],
                             [{'type': 'payload', 'payload': payload}])

    def test_sin_botones_solo_body(self):
        rec = self.Outbound.queue_template(
            self.company, '0996706629', 'aviso_agenda', ['Ana', 'x'])
        self.assertEqual(
            [c['type'] for c in rec.meta_payload['template']['components']],
            ['body'])

    def test_registra_origen(self):
        rec = self.Outbound.queue_template(
            self.company, '0996706629', 'aviso_agenda', ['Ana', 'prueba'],
            origin=self.company)
        self.assertEqual(rec.res_model, 'res.company')
        self.assertEqual(rec.res_id, self.company.id)

    def test_numero_invalido_no_encola(self):
        rec = self.Outbound.queue_template(
            self.company, '12345', 'aviso_agenda', ['Ana', 'x'])
        self.assertFalse(rec)
        self.assertFalse(self.Outbound.search_count(
            [('company_id', '=', self.company.id)]))


class TestDispatcher(TestWaOutboundBase):

    def setUp(self):
        super().setUp()
        icp = self.env['ir.config_parameter'].sudo()
        icp.set_param('innatum_wa.outbound_enabled', 'True')
        icp.set_param('innatum_wa.outbound_webhook_url',
                      'https://n8n.test/webhook/whatsapp-outbound')
        icp.set_param('innatum_wa.outbound_shared_secret', 'secreto-test')
        self.rec = self.Outbound.queue_template(
            self.company, '0996706629', 'aviso_agenda', ['Ana', 'prueba'])

    def _mock_response(self, status=200, body=None):
        resp = Mock()
        resp.status_code = status
        resp.content = b'{}'
        resp.json.return_value = body if body is not None else {}
        return resp

    def _patch_post(self):
        return patch(
            'odoo.addons.innatum_agenda_ai.models.wa_outbound.requests.post')

    def test_envio_exitoso(self):
        with self._patch_post() as post:
            post.return_value = self._mock_response(
                200, {'ok': True, 'wamid': 'wamid.ABC'})
            enviados = self.Outbound._dispatch_pending()
        self.assertEqual(enviados, 1)
        self.assertEqual(self.rec.state, 'sent')
        self.assertEqual(self.rec.wamid, 'wamid.ABC')
        kwargs = post.call_args.kwargs
        self.assertEqual(
            kwargs['headers']['X-Innatum-Outbound-Token'], 'secreto-test')
        self.assertEqual(kwargs['json']['phone_number_id'], '111222333444')
        self.assertEqual(kwargs['json']['to'], '593996706629')
        self.assertEqual(kwargs['json']['payload'], self.rec.meta_payload)
        self.assertFalse(self.rec.next_attempt_at)

    def test_error_retryable_programa_backoff(self):
        with self._patch_post() as post:
            post.return_value = self._mock_response(
                200, {'ok': False, 'status': 500,
                      'error': 'boom', 'retryable': True})
            self.Outbound._dispatch_pending()
        self.assertEqual(self.rec.state, 'pending')
        self.assertEqual(self.rec.attempts, 1)
        self.assertTrue(self.rec.next_attempt_at)
        self.assertIn('boom', self.rec.error_message)
        # En backoff: una segunda pasada NO debe reintentarlo todavía.
        with self._patch_post() as post:
            self.assertEqual(self.Outbound._dispatch_pending(), 0)
            post.assert_not_called()

    def test_error_permanente_falla_de_inmediato(self):
        with self._patch_post() as post:
            post.return_value = self._mock_response(
                200, {'ok': False, 'status': 400,
                      'error': 'template not found', 'retryable': False})
            self.Outbound._dispatch_pending()
        self.assertEqual(self.rec.state, 'failed')
        self.assertEqual(self.rec.attempts, 1)

    def test_excepcion_de_red_es_retryable(self):
        import requests as requests_lib
        with self._patch_post() as post:
            post.side_effect = requests_lib.ConnectionError('sin red')
            self.Outbound._dispatch_pending()
        self.assertEqual(self.rec.state, 'pending')
        self.assertEqual(self.rec.attempts, 1)

    def test_http_no_200_es_retryable(self):
        with self._patch_post() as post:
            post.return_value = self._mock_response(502, {})
            self.Outbound._dispatch_pending()
        self.assertEqual(self.rec.state, 'pending')
        self.assertEqual(self.rec.attempts, 1)

    def test_reintentos_agotados_falla(self):
        self.rec.attempts = 5  # MAX_RETRIES ya consumidos
        with self._patch_post() as post:
            post.return_value = self._mock_response(
                200, {'ok': False, 'status': 500, 'error': 'x',
                      'retryable': True})
            self.Outbound._dispatch_pending()
        self.assertEqual(self.rec.state, 'failed')

    def test_kill_switch(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'innatum_wa.outbound_enabled', 'False')
        with self._patch_post() as post:
            self.assertEqual(self.Outbound._dispatch_pending(), 0)
            post.assert_not_called()
        self.assertEqual(self.rec.state, 'pending')

    def test_tenant_sin_phone_number_id_falla_permanente(self):
        self.company.wa_phone_number_id = False
        with self._patch_post() as post:
            self.Outbound._dispatch_pending()
            post.assert_not_called()
        self.assertEqual(self.rec.state, 'failed')

    def test_sending_atascado_se_recupera(self):
        self.rec.write({'state': 'sending'})
        # Volcar el write pendiente antes del SQL crudo: si no, el flush
        # posterior pisaría el write_date envejecido con el del ORM.
        self.env.flush_all()
        # Envejecer el write_date por SQL (el ORM no permite escribirlo).
        self.env.cr.execute(
            "UPDATE innatum_wa_outbound "
            "SET write_date = (now() at time zone 'UTC') - interval '20 minutes' "
            "WHERE id = %s", [self.rec.id])
        self.env.invalidate_all()
        with self._patch_post() as post:
            post.return_value = self._mock_response(
                200, {'ok': True, 'wamid': 'wamid.REC'})
            enviados = self.Outbound._dispatch_pending()
        self.assertEqual(enviados, 1)
        self.assertEqual(self.rec.state, 'sent')

    def test_sending_reciente_no_se_toca(self):
        self.rec.write({'state': 'sending'})  # write_date = ahora
        with self._patch_post() as post:
            self.assertEqual(self.Outbound._dispatch_pending(), 0)
            post.assert_not_called()
        self.assertEqual(self.rec.state, 'sending')

    def test_backoff_primer_fallo_es_1_minuto(self):
        from datetime import timedelta
        from odoo import fields as odoo_fields
        antes = odoo_fields.Datetime.now()
        with self._patch_post() as post:
            post.return_value = self._mock_response(
                200, {'ok': False, 'status': 500, 'error': 'x',
                      'retryable': True})
            self.Outbound._dispatch_pending()
        delta = self.rec.next_attempt_at - antes
        self.assertTrue(timedelta(seconds=30) <= delta <= timedelta(minutes=2),
                        'El primer reintento debe programarse ~1 minuto después')


class TestCron(TestWaOutboundBase):

    def test_cron_existe_y_llama_al_dispatcher(self):
        cron = self.env.ref('innatum_agenda_ai.ir_cron_wa_outbound_dispatch')
        self.assertTrue(cron.active)
        self.assertEqual(cron.model_id.model, 'innatum.wa.outbound')
        self.assertIn('_dispatch_pending', cron.code)

    def test_encolar_dispara_trigger(self):
        cron = self.env.ref('innatum_agenda_ai.ir_cron_wa_outbound_dispatch')
        Trigger = self.env['ir.cron.trigger'].sudo()
        antes = Trigger.search_count([('cron_id', '=', cron.id)])
        self.Outbound.queue_template(
            self.company, '0996706629', 'aviso_agenda', ['Ana', 'x'])
        despues = Trigger.search_count([('cron_id', '=', cron.id)])
        self.assertEqual(despues, antes + 1)


class TestRequeue(TestWaOutboundBase):

    def test_requeue_resetea_fallido(self):
        rec = self.Outbound.queue_template(
            self.company, '0996706629', 'aviso_agenda', ['Ana', 'x'])
        rec.write({'state': 'failed', 'attempts': 6,
                   'error_message': 'agotado'})
        rec.action_requeue()
        self.assertEqual(rec.state, 'pending')
        self.assertEqual(rec.attempts, 0)
        self.assertFalse(rec.next_attempt_at)
        self.assertFalse(rec.error_message)

    def test_requeue_ignora_no_fallidos(self):
        rec = self.Outbound.queue_template(
            self.company, '0996706629', 'aviso_agenda', ['Ana', 'x'])
        rec.write({'state': 'sent'})
        rec.action_requeue()
        self.assertEqual(rec.state, 'sent')


class TestCancelar(TestWaOutboundBase):

    def test_cancela_pendiente(self):
        rec = self.Outbound.queue_template(
            self.company, '0996706629', 'aviso_agenda', ['Ana', 'x'])
        rec.action_cancel_message()
        self.assertEqual(rec.state, 'cancelled')
        self.assertFalse(rec.next_attempt_at)

    def test_cancela_fallido(self):
        rec = self.Outbound.queue_template(
            self.company, '0996706629', 'aviso_agenda', ['Ana', 'x'])
        rec.write({'state': 'failed', 'attempts': 3})
        rec.action_cancel_message()
        self.assertEqual(rec.state, 'cancelled')

    def test_ignora_enviado(self):
        rec = self.Outbound.queue_template(
            self.company, '0996706629', 'aviso_agenda', ['Ana', 'x'])
        rec.write({'state': 'sent'})
        rec.action_cancel_message()
        self.assertEqual(rec.state, 'sent')

    def test_cancelado_no_lo_toma_el_dispatcher(self):
        icp = self.env['ir.config_parameter'].sudo()
        icp.set_param('innatum_wa.outbound_enabled', 'True')
        icp.set_param('innatum_wa.outbound_webhook_url',
                      'https://n8n.test/webhook/whatsapp-outbound')
        icp.set_param('innatum_wa.outbound_shared_secret', 'secreto-test')
        rec = self.Outbound.queue_template(
            self.company, '0996706629', 'aviso_agenda', ['Ana', 'x'])
        rec.action_cancel_message()
        with patch(
                'odoo.addons.innatum_agenda_ai.models.wa_outbound.'
                'requests.post') as post:
            enviados = self.Outbound._dispatch_pending()
            post.assert_not_called()
        self.assertEqual(enviados, 0)
        self.assertEqual(rec.state, 'cancelled')
