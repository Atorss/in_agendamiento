# -*- coding: utf-8 -*-

from odoo import models, fields, api, tools


class InnatumAgendaCalendario(models.Model):
    """Calendario unificado (solo lectura): turnos + bloqueos en una sola
    vista, para que el operador vea TODO junto (ocupación real del
    profesional). Es una vista SQL (UNION); crear turnos/bloqueos se hace
    desde sus modelos. El id de los bloqueos se desplaza +1e9 para no
    colisionar con el de los turnos dentro de la vista.
    """
    _name = 'innatum.agenda.calendario'
    _description = 'Calendario unificado (turnos + bloqueos)'
    _auto = False
    _order = 'date_start desc'

    name = fields.Char(string='Título', readonly=True)
    tipo = fields.Selection(
        [('turno', 'Turno'), ('bloqueo', 'Bloqueo')],
        string='Tipo', readonly=True)
    professional_id = fields.Many2one('hr.employee', string='Profesional', readonly=True)
    company_id = fields.Many2one('res.company', string='Empresa', readonly=True)
    partner_id = fields.Many2one('res.partner', string='Cliente', readonly=True)
    servicio_id = fields.Many2one('innatum.agenda.servicio', string='Servicio', readonly=True)
    date_start = fields.Datetime(string='Inicio', readonly=True)
    date_end = fields.Datetime(string='Fin', readonly=True)
    estado = fields.Char(string='Estado', readonly=True)
    color = fields.Integer(string='Color', readonly=True)
    res_id = fields.Integer(string='Id real', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW innatum_agenda_calendario AS (
                SELECT
                    t.id AS id,
                    'turno' AS tipo,
                    t.name AS name,
                    t.professional_id AS professional_id,
                    t.company_id AS company_id,
                    t.partner_id AS partner_id,
                    t.servicio_id AS servicio_id,
                    t.date_start AS date_start,
                    t.date_end AS date_end,
                    t.state AS estado,
                    COALESCE(s.color, 0) AS color,
                    t.id AS res_id
                FROM innatum_agenda_turno t
                LEFT JOIN innatum_agenda_servicio s ON s.id = t.servicio_id
                WHERE t.state != 'cancelled'
                UNION ALL
                SELECT
                    (b.id + 1000000000) AS id,
                    'bloqueo' AS tipo,
                    b.name AS name,
                    b.professional_id AS professional_id,
                    b.company_id AS company_id,
                    NULL::integer AS partner_id,
                    NULL::integer AS servicio_id,
                    b.date_start AS date_start,
                    b.date_end AS date_end,
                    'bloqueo' AS estado,
                    COALESCE(b.color, 9) AS color,
                    b.id AS res_id
                FROM innatum_agenda_bloqueo b
            )
        """)


class InnatumAgendaCalendarioFiltro(models.Model):
    """Estado, por usuario, del filtro lateral de profesionales del calendario
    unificado. Es el 'write_model' del campo professional_id (filters="1") en
    la vista calendario: guarda qué profesionales tiene marcados cada usuario.

    La primera vez se siembra el profesional del propio usuario (marcado), así
    el calendario abre mostrando SOLO sus turnos; desde el panel lateral el
    usuario puede agregar a otros profesionales o marcar "Todo" para ver a
    todos. El panel solo lista los profesionales que el usuario haya agregado
    (mecánica estándar del calendario de Odoo con write_model)."""
    _name = 'innatum.agenda.calendario.filtro'
    _description = 'Filtro de profesional del calendario (por usuario)'

    user_id = fields.Many2one(
        'res.users', string='Usuario', required=True, ondelete='cascade',
        index=True, default=lambda self: self.env.uid,
    )
    professional_id = fields.Many2one(
        'hr.employee', string='Profesional', required=True,
        ondelete='cascade', index=True,
    )
    checked = fields.Boolean(string='Visible', default=True)

    _sql_constraints = [
        ('user_professional_uniq', 'unique(user_id, professional_id)',
         'Ya existe un filtro de este profesional para el usuario.'),
    ]

    @api.model
    def _seed_default(self):
        """Siembra el filtro propio (profesional del usuario logueado, marcado)
        la primera vez, si el usuario aún no tiene ninguno. Con esto el
        calendario abre filtrado por defecto al profesional logueado."""
        if self.search_count([('user_id', '=', self.env.uid)]):
            return
        emp = self.env['hr.employee'].sudo().search(
            [('user_id', '=', self.env.uid)], limit=1)
        if emp:
            self.sudo().create({
                'user_id': self.env.uid,
                'professional_id': emp.id,
                'checked': True,
            })

    @api.model
    def search_read(self, domain=None, fields=None, offset=0, limit=None,
                    order=None, **read_kwargs):
        # El calendario pide los filtros del usuario con searchRead: es el
        # momento de sembrar el filtro propio la primera vez.
        self._seed_default()
        return super().search_read(
            domain=domain, fields=fields, offset=offset, limit=limit,
            order=order, **read_kwargs)
