"""Canonical request signatures; never infer original requests from mutable history."""
import hashlib
import json
from .domain import DomainError


def signature(values):
    try:
        payload = json.dumps({k: v for k, v in values.items() if k != 'operation_key'},
                             sort_keys=True, ensure_ascii=True, separators=(',', ':'), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise DomainError('Envie valores JSON válidos.') from error
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def check_repeat(saved, incoming):
    if saved is None:
        raise DomainError('Esta operação é anterior à proteção de reenvios. Confira o histórico antes de registrar novamente.', 409)
    if saved != incoming:
        raise DomainError('Este identificador já foi usado com outros dados. Confira o registro no histórico; o reenvio não foi salvo.', 409)
