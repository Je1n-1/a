"""Exportação local de blocos planejados no formato iCalendar (RFC 5545)."""
from __future__ import annotations

from datetime import date, datetime, timedelta


def _escape(value) -> str:
    """Escapa texto de iCalendar sem transformar dados do usuário em sintaxe."""
    return str(value or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n")


def _fold(line: str) -> list[str]:
    """Dobra linhas longas de forma conservadora para leitores RFC 5545."""
    encoded = line.encode("utf-8")
    if len(encoded) <= 75:
        return [line]
    result, current = [], ""
    size = 0
    for char in line:
        char_size = len(char.encode("utf-8"))
        if size + char_size > 74:
            result.append(current)
            current, size = " " + char, 1 + char_size
        else:
            current += char
            size += char_size
    if current:
        result.append(current)
    return result


def _lines(*values: str) -> list[str]:
    result: list[str] = []
    for value in values:
        result.extend(_fold(value))
    return result


def calendar_ics(blocks, *, timezone: str, calendar_name: str = "plano.") -> str:
    """Monta um calendário com blocos planejados, sem depender de OAuth.

    Os IDs dos blocos tornam o ``UID`` estável: exportar novamente atualiza o
    mesmo evento para clientes que aceitam importações incrementais, em vez de
    criar cópias ambíguas. Blocos sem horário continuam úteis como eventos de
    dia inteiro.
    """
    rows = [dict(block) for block in blocks]
    output = _lines(
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//plano//Planejamento de estudos//PT-BR",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape(calendar_name)}",
        f"X-WR-TIMEZONE:{_escape(timezone)}",
    )
    for block in rows:
        day = date.fromisoformat(str(block["scheduled_date"]))
        subject = block.get("subject_name") or block.get("name") or "Estudo"
        topic = block.get("topic_name")
        formation = block.get("formation_name")
        reason = block.get("selection_reason") or block.get("reason")
        duration = max(1, int(block.get("planned_duration_minutes") or 1))
        title = f"{subject} — {topic}" if topic else subject
        description_bits = []
        if formation:
            description_bits.append(f"Formação: {formation}")
        if topic:
            description_bits.append(f"Tópico: {topic}")
        if reason:
            description_bits.append(f"Motivo: {reason}")
        description_bits.append(f"Duração planejada: {duration} min")
        output.extend(_lines("BEGIN:VEVENT", f"UID:planned-{int(block['id'])}@plano.local"))
        output.extend(_lines(f"SUMMARY:{_escape(title)}", f"DESCRIPTION:{_escape(chr(10).join(description_bits))}"))
        if block.get("start_time"):
            started = datetime.combine(day, datetime.strptime(str(block["start_time"]), "%H:%M").time())
            ended = started + timedelta(minutes=duration)
            output.extend(_lines(
                f"DTSTART;TZID={timezone}:{started.strftime('%Y%m%dT%H%M%S')}",
                f"DTEND;TZID={timezone}:{ended.strftime('%Y%m%dT%H%M%S')}",
            ))
        else:
            output.extend(_lines(
                f"DTSTART;VALUE=DATE:{day.strftime('%Y%m%d')}",
                f"DTEND;VALUE=DATE:{(day + timedelta(days=1)).strftime('%Y%m%d')}",
            ))
        output.extend(_lines("END:VEVENT"))
    output.extend(_lines("END:VCALENDAR"))
    return "\r\n".join(output) + "\r\n"
