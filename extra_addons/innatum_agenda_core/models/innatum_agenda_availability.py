# -*- coding: utf-8 -*-
"""Disponibilidad on-demand para el modo de agenda 'directa'.

Disponibilidad = horario de trabajo del profesional (resource.calendar)
MENOS (turnos no cancelados + bloqueos). Los turnos NO se pre-generan: se
crean al agendar. Stateless: recibe todo por parámetro; trabaja en datetime
naive UTC (igual que el almacenamiento de Odoo).
"""

import logging
from datetime import datetime, timedelta

import pytz

from odoo import models, api
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class InnatumAgendaAvailability(models.AbstractModel):
    _name = 'innatum.agenda.availability'
    _description = 'Disponibilidad on-demand (modo directo)'

    # ------------------------------------------------------------------
    # Intervalos ocupados / laborables (naive UTC)
    # ------------------------------------------------------------------

    @api.model
    def _busy_intervals(self, professional, dt_from, dt_to):
        """Turnos no cancelados + bloqueos que solapan la ventana."""
        Turno = self.env['innatum.agenda.turno'].sudo()
        Bloqueo = self.env['innatum.agenda.bloqueo'].sudo()
        busy = []
        for t in Turno.search([
            ('professional_id', '=', professional.id),
            ('state', '!=', 'cancelled'),
            ('date_start', '<', dt_to),
            ('date_end', '>', dt_from),
        ]):
            if t.date_start and t.date_end:
                busy.append((t.date_start, t.date_end))
        for b in Bloqueo.search([
            ('professional_id', '=', professional.id),
            ('date_start', '<', dt_to),
            ('date_end', '>', dt_from),
        ]):
            busy.append((b.date_start, b.date_end))
        return busy

    @api.model
    def _work_intervals(self, professional, dt_from, dt_to):
        """Intervalos laborables (naive UTC) desde el resource.calendar del
        profesional (o el de la empresa). Vacío si no hay calendario."""
        cal = (professional.resource_calendar_id
               or professional.company_id.resource_calendar_id)
        if not cal or not professional.resource_id:
            return []
        # sudo: en canales públicos (web/chatbot) el usuario puede no tener
        # permiso de lectura sobre resource.calendar; el aislamiento por tenant
        # ya lo garantiza que el calendario pertenece a la empresa del
        # profesional (record rule + asignación por empresa).
        cal = cal.sudo()
        start = pytz.UTC.localize(dt_from)
        end = pytz.UTC.localize(dt_to)
        by_resource = cal._work_intervals_batch(
            start, end, resources=professional.resource_id,
        )
        intervals = by_resource.get(professional.resource_id.id) \
            or by_resource.get(False)
        out = []
        for item in (intervals or []):
            s, e = item[0], item[1]
            out.append((
                s.astimezone(pytz.UTC).replace(tzinfo=None),
                e.astimezone(pytz.UTC).replace(tzinfo=None),
            ))
        return out

    @api.model
    def _subtract(self, base, subs):
        """Resta los intervalos `subs` de `base`. Devuelve los huecos libres."""
        subs = sorted([(s, e) for s, e in subs if e > s])
        free = []
        for bs, be in sorted(base):
            cur = bs
            for ss, se in subs:
                if se <= cur or ss >= be:
                    continue
                if ss > cur:
                    free.append((cur, min(ss, be)))
                cur = max(cur, se)
                if cur >= be:
                    break
            if cur < be:
                free.append((cur, be))
        return [f for f in free if f[1] > f[0]]

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    @api.model
    def free_slots(self, professional, servicio, dt_from, dt_to,
                   duration_min=None, granularity_min=15):
        """Inicios de slot (naive UTC) donde cabe un turno de `duration_min`
        (o servicio.duracion) para el profesional, dentro de [dt_from, dt_to].
        """
        dur = int(duration_min or (servicio.duracion if servicio else 0) or 30)
        work = self._work_intervals(professional, dt_from, dt_to)
        if not work:
            return []
        busy = self._busy_intervals(professional, dt_from, dt_to)
        free = self._subtract(work, busy)
        now = datetime.utcnow()
        floor = max(now, dt_from)
        step = timedelta(minutes=granularity_min)
        dur_td = timedelta(minutes=dur)
        slots = []
        for fs, fe in free:
            cur = fs
            while cur + dur_td <= fe:
                if cur >= floor:
                    slots.append(cur)
                cur += step
        return sorted(slots)

    @api.model
    def create_turno(self, professional, servicio, date_start, partner=None,
                     duracion_override=0, motivo=None, state='reserved'):
        """Crea un turno on-demand validando solape con turnos y bloqueos.

        El solape con otros TURNOS lo cubre el constraint `_check_no_overlap`
        del turno; aquí validamos además contra BLOQUEOS. Devuelve el turno
        creado o lanza ValidationError.
        """
        Turno = self.env['innatum.agenda.turno'].sudo()
        dur = int(duracion_override or (servicio.duracion if servicio else 0) or 30)
        date_end = date_start + timedelta(minutes=dur)
        conflicto = self.env['innatum.agenda.bloqueo'].sudo().search([
            ('professional_id', '=', professional.id),
            ('date_start', '<', date_end),
            ('date_end', '>', date_start),
        ], limit=1)
        if conflicto:
            raise ValidationError(
                'El horario coincide con un bloqueo del profesional (%s).'
                % (conflicto.motivo or conflicto.name))
        vals = {
            'professional_id': professional.id,
            'servicio_id': servicio.id if servicio else False,
            'servicio_ids': [(6, 0, servicio.ids)] if servicio else False,
            'date_start': date_start,
            'state': state,
            'publicar': False,
        }
        if duracion_override:
            vals['duracion_override'] = duracion_override
        if partner:
            vals['partner_id'] = partner.id
        if motivo:
            vals['notes'] = motivo
        return Turno.create(vals)
