"""Browser isolation for the loopback-only app; not user authentication."""
from urllib.parse import urlsplit
from flask import jsonify, request


def origin_tuple(value, *, origin_header=False):
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username is not None or parsed.password is not None:
            return None
        if origin_header and (parsed.path or parsed.query or parsed.fragment):
            return None
        return parsed.scheme, parsed.hostname.lower(), parsed.port or (443 if parsed.scheme == 'https' else 80)
    except ValueError:
        return None


def protect_request():
    expected = origin_tuple(request.host_url)
    if not expected or expected[1] not in ('localhost', '127.0.0.1'):
        return jsonify(error='Aplicação disponível somente no endereço local.'), 403
    if request.remote_addr not in ('127.0.0.1', '::1'):
        return jsonify(error='Acesso permitido somente neste computador.'), 403
    site = request.headers.get('Sec-Fetch-Site')
    if site is not None and site not in ('same-origin', 'none'):
        return jsonify(error='Abra o Plano diretamente no endereço local.'), 403
    origin = request.headers.get('Origin')
    referer = request.headers.get('Referer')
    if origin is not None and origin_tuple(origin, origin_header=True) != expected:
        return jsonify(error='Origem da requisição não permitida.'), 403
    if referer is not None and origin_tuple(referer) != expected:
        return jsonify(error='Origem da página não permitida.'), 403
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        if site == 'none':
            return jsonify(error='Abra o formulário dentro do Plano.'), 403
        # JSON APIs cannot be submitted by simple cross-origin HTML forms.
        # Multipart uploads additionally require a non-safelisted header.
        if not request.is_json and request.headers.get('X-Plano-Request') != '1':
            return jsonify(error='Atualize a página do Plano antes de enviar o arquivo.'), 403


def protect_response(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Cross-Origin-Resource-Policy'] = 'same-origin'
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
    # Inline styles are used for chart dimensions, never for scripts.
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
        "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    )
    if request.endpoint != 'static':
        response.headers['Cache-Control'] = 'no-store'
    response.vary.add('Origin')
    response.vary.add('Sec-Fetch-Site')
    return response
