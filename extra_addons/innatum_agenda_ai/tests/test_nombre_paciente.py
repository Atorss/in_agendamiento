# -*- coding: utf-8 -*-
"""Calidad del NOMBRE del paciente.

Producción saludó con "¡Hola 21! 👋": el partner quedó con un nombre basura
creado por la ruta del LLM (`identificar_cliente` no validaba el nombre,
mientras la ruta determinista sí exige 3+ caracteres). Dos defensas:
no crear partners con nombres inválidos, y no saludar con basura si ya
existe un registro así.
"""
from .common_wa_fase2 import Fase2Case


class TestNombreValidacion(Fase2Case):

    def setUp(self):
        super().setUp()
        self.Tools = self.env['flow.scheduling.tools']
        self.session = self.Session.create({
            'company_id': self.company.id, 'wa_from': '593990070007',
        })

    def _identificar(self, **params):
        return self.Tools.identificar_cliente(params, session=self.session)

    def test_nombre_solo_digitos_no_crea_partner(self):
        res = self._identificar(name='21', vat='1710034065')
        partner = self.env['res.partner'].sudo().browse(
            res.get('partner_id') or 0)
        if partner.exists():
            self.assertNotEqual(
                partner.name, '21',
                'Se creó un partner llamado "21": el saludo dirá "¡Hola 21!"')

    def test_nombre_muy_corto_no_crea_partner(self):
        res = self._identificar(name='ab', vat='1710034065')
        partner = self.env['res.partner'].sudo().browse(
            res.get('partner_id') or 0)
        if partner.exists():
            self.assertNotEqual(partner.name, 'ab')

    def test_nombre_valido_si_crea(self):
        res = self._identificar(name='Lucía Andrade', vat='1710034065')
        self.assertTrue(res.get('partner_id'))
        partner = self.env['res.partner'].sudo().browse(res['partner_id'])
        self.assertEqual(partner.name, 'Lucía Andrade')

    def test_edad_no_se_toma_como_nombre(self):
        """El caso real: el LLM tomó un número de la conversación."""
        res = self._identificar(name='21 años', vat='1710034065')
        partner = self.env['res.partner'].sudo().browse(
            res.get('partner_id') or 0)
        if partner.exists():
            self.assertFalse(
                partner.name.strip().startswith('21'),
                'El nombre no debe empezar con un número: el saludo usa la '
                'primera palabra → "¡Hola 21!"')


class TestSaludoConNombreBasura(Fase2Case):
    """Defensa 2: aunque YA exista un partner con nombre basura (dato viejo),
    el saludo no debe leerse ridículo."""

    def _saludo_de(self, nombre):
        partner = self.env['res.partner'].create({
            'name': nombre, 'company_id': self.company.id,
            'mobile': '0991110000',
        })
        session = self.Session.create({
            'company_id': self.company.id, 'wa_from': '593990080008',
            'partner_id': partner.id,
        })
        session.action_set_state('menu_principal')
        return self.Agent.process_message(
            session, 'hola', wamid='W_NOM_%s' % nombre)['response_text']

    def test_no_saluda_con_numero(self):
        self.assertNotIn('Hola 21', self._saludo_de('21'))

    def test_no_saluda_con_numero_compuesto(self):
        self.assertNotIn('Hola 21', self._saludo_de('21 años'))

    def test_saluda_normal_con_nombre_real(self):
        self.assertIn('Hola Lucía', self._saludo_de('Lucía Andrade'))
