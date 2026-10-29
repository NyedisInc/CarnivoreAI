
from __future__ import annotations

import re

BODY_MARGIN: int = 16

_BODY_GAP = r"(?:\s|\\[bfnrt])*"

OP_SERVICE_ACCOUNT = re.compile(
    r"ops_(?=[a-z0-9+/=_-]*[A-Z])[A-Za-z0-9+/=_-]{40,}"
)

GITHUB_TOKEN = re.compile(
    r"(?:github_pat_\w{82,%d}|gh[pousr]_[A-Za-z0-9]{36,%d})"
    % (82 + BODY_MARGIN, 255 + BODY_MARGIN)
)

AWS_ACCESS_KEY_ID = re.compile(
    r"(?:AKIA|ASIA|ABIA|ACCA|AGPA|AIDA|AIPA|ANPA|ANVA|AROA)[A-Z0-9]{16,%d}"
    % (16 + BODY_MARGIN)
)

AWS_SECRET_ACCESS_KEY = re.compile(
    r"""(?ix)
    aws[A-Za-z0-9_.\-]{0,64}(?:secret|access)[A-Za-z0-9_.\-]{0,64}
    [^\w\r\n]{0,8}? [:=] [^\w\r\n]{0,8}?
    (?P<value>[A-Za-z0-9/+=]{40,%d})
    """ % (40 + BODY_MARGIN)
)

GOOGLE_API_KEY = re.compile(r"AIza[0-9A-Za-z_\-]{35,%d}" % (35 + BODY_MARGIN))

SLACK_TOKEN = re.compile(r"xox[abprs]-[A-Za-z0-9\-]{10,}")

STRIPE_KEY = re.compile(r"[rs]k_(?:live|test)_[A-Za-z0-9]{24,%d}" % (99 + BODY_MARGIN))

HUGGINGFACE_TOKEN = re.compile(r"hf_[A-Za-z0-9]{30,%d}" % (40 + BODY_MARGIN))

NPM_TOKEN = re.compile(r"npm_[A-Za-z0-9]{36,%d}" % (36 + BODY_MARGIN))

GITLAB_TOKEN = re.compile(r"glpat-[A-Za-z0-9_\-]{20,%d}" % (50 + BODY_MARGIN))

SENDGRID_KEY = re.compile(r"SG\.[A-Za-z0-9_\-]{22}\.[A-Za-z0-9_\-]{43}")

SLACK_APP_TOKEN = re.compile(r"xapp-[A-Za-z0-9\-]{10,}")

CARNIVORE_API_KEY = re.compile(r"cak_[A-Za-z0-9_\-]{43,%d}" % (43 + BODY_MARGIN))

CATALOG_BOT_TOKEN = re.compile(r"cbt_[A-Za-z0-9_\-]{43,%d}" % (43 + BODY_MARGIN))

PEM_PRIVATE_KEY = re.compile(
    r"-----BEGIN[A-Z0-9 ]*PRIVATE ?KEY-----"
    r"(?=" + _BODY_GAP + r"[A-Za-z0-9+/=]{20,})"
)

CLOUDFLARE_API_TOKEN = re.compile(
    r"""(?ix)
    (?: cloudflare | cf ) [A-Za-z0-9_.\-]{0,64}
    (?: token | key | secret )
    [^\w\r\n]{0,8}? [:=] [^\w\r\n]{0,8}?
    (?P<value>[A-Za-z0-9_\-]{37,%d})
    """ % (40 + BODY_MARGIN)
)

MINISIGN_SECRET_KEY = re.compile(
    r"untrusted ?comment:? *minisign ?encrypted ?secret ?key"
    r"(?=" + _BODY_GAP + r"[A-Za-z0-9+/=]{20,})"
)

ANTHROPIC_API_KEY = re.compile(
    r"sk-ant-(?:api|admin|oat|ort)[0-9]{2}-[A-Za-z0-9_\-]{32,%d}"
    % (255 + BODY_MARGIN)
)

OPENAI_API_KEY = re.compile(
    r"sk-(?:proj|svcacct|admin)-[A-Za-z0-9_\-]{40,%d}" % (255 + BODY_MARGIN)
)

BEARER_TOKEN = re.compile(
    r"(?i:bearer)[ \t]+(?P<value>[A-Za-z0-9._~+/\-]{20,%d}=*)" % (512 + BODY_MARGIN)
)

JWT = re.compile(
    r"(?P<value>eyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,})"
)

VENDOR_MARKER_RE = re.compile(
    r"ops_|gh[pousr]_|github_"
    r"|AKIA|ASIA|ABIA|ACCA|AGPA|AIDA|AIPA|ANPA|ANVA|AROA"
    r"|AIza|xox[abprs]-|sk-|-----BEGIN|minisign|eyJ|(?i:bearer)|cak_"
    r"|(?i:aws|cloudflare|cf)[A-Za-z0-9_.\-]{0,64}(?i:secret|access|token|key)"
)

SPAN_MARKER_RE = re.compile(
    r"ops_|gh[pousr]_|github_pat_"
    r"|AKIA|ASIA|ABIA|ACCA|AGPA|AIDA|AIPA|ANPA|ANVA|AROA"
    r"|AIza|xox[abprs]-|sk-ant-(?:api|admin|oat|ort)[0-9]{2}-"
    r"|sk-(?:proj|svcacct|admin)-|cak_"
)

STAND_IN_BODY: str = "Q7W2E9R4T6Y1U8I3O5P0ZXCVBNMLKJHGFDSA"
