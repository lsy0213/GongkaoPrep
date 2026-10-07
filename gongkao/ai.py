"""AI 助教（可选）：申论批改、题目讲解、面试点评、自由提问。

支持 OpenAI 兼容接口（DeepSeek / 通义千问 / Kimi / 智谱 / OpenAI 等，标准库 urllib 直连）
和 Claude（走 anthropic SDK，需要 `pip install anthropic`）。在软件「设置 → AI 助教」里选服务商、
填 API Key；Claude 也可以改为设置环境变量 ANTHROPIC_API_KEY。没配置时其余功能照常使用。
"""

import json
import os
import re
import urllib.error
import urllib.request

try:
    import anthropic
except ImportError:  # 没装 SDK 时 Claude 不可用，其余服务商和功能不受影响
    anthropic = None

# type: "openai" 表示 OpenAI 兼容的 /chat/completions 接口；"anthropic" 表示 Claude
PRESETS = {
    "none": {"name": "不使用 AI", "type": "none", "base_url": "", "model": ""},
    "deepseek": {
        "name": "DeepSeek",
        "type": "openai",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
    },
    "qwen": {
        "name": "通义千问",
        "type": "openai",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
    },
    "kimi": {
        "name": "Kimi（月之暗面）",
        "type": "openai",
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-32k",  # 申论材料较长，8k 上下文不够用
    },
    "zhipu": {
        "name": "智谱 GLM",
        "type": "openai",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-flash",
    },
    "openai": {
        "name": "OpenAI",
        "type": "openai",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
    },
    "claude": {
        "name": "Claude（Anthropic）",
        "type": "anthropic",
        "base_url": "",
        "model": "claude-opus-5-5",
    },
    "custom": {
        "name": "自定义（OpenAI 兼容）",
        "type": "openai",
        "base_url": "",
        "model": "",
    },
}

TIMEOUT = 180

SYSTEM = (
    "你是一位经验丰富的中国公务员考试辅导老师，熟悉国考和各省省考的行测、申论和结构化面试。"
    "学员是零基础开始备考的考生。讲解要准确、具体、可操作，用简体中文，适当使用小标题和列表，"
    "不要编造具体政策文件的原文或数据；涉及最新政策、考试安排时，提醒以官方发布为准。"
)


class AIError(Exception):
    pass


# 申论批改的固定评分细则：每次按同一套标准给分，分数才能前后比较、画走势
ESSAY_RUBRIC = """请严格按下面的评分细则批改（国考 / 省考阅卷的常见做法，从严）：
- 要点分（占满分的 70%）：把参考要点平均分配分值；答到给全分，答到一半给一半，没答到不给；要点之外的合理内容最多补 1 分。
- 结构分（15%）：分条或分层清楚、有总括句、对策类有主体和措施对应。
- 语言分（15%）：用规范的申论语言、简洁准确；照抄材料原句过多扣分。
- 字数：超出字数上限的部分不给分；明显不足字数下限的，结构分和语言分减半。

输出格式（第一行必须严格是这个格式，软件要读取分数）：
【得分】x / {full}
然后依次写：
1. 一句话总评。
2. 要点核对：逐条对照参考要点，标「已答到 / 部分答到 / 遗漏」，并写出这条给了几分。
3. 结构分、语言分各给了几分，扣在哪里。
4. 最影响得分的 2–4 个问题和可以直接照着改的修改建议。
5. 示范：按要求重写一段高分作答（控制在字数要求内）。"""

SCORE_LINE_RE = re.compile(r"【得分】\s*(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)")


def parse_essay_score(text):
    """从 AI 批改结果第一行读出 (得分, 满分)；读不到返回 (None, None)。"""
    m = SCORE_LINE_RE.search((text or "")[:400])
    if not m:
        return None, None
    score, full = float(m.group(1)), float(m.group(2))
    if full <= 0 or score > full * 1.05:
        return None, None
    return min(score, full), full


def estimate_tokens(text):
    """服务商没返回用量时的估算：中文约 1.5 字一个 token，英文约 4 个字母一个 token。"""
    text = text or ""
    cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
    return int(cjk / 1.5 + (len(text) - cjk) / 4) + 1


def config(settings):
    """从设置里整理出实际要用的服务商配置。

    旧版本只有 Claude、没有 ai_provider 这一项：已存过 Key（或设了环境变量）就当作 Claude。
    """
    provider = settings.get("ai_provider") or ""
    if provider not in PRESETS:
        has_old = settings.get("ai_api_key") or os.environ.get("ANTHROPIC_API_KEY")
        provider = "claude" if has_old else "none"
    pr = PRESETS[provider]
    key = settings.get("ai_api_key") or ""
    if not key and pr["type"] == "anthropic":
        key = os.environ.get("ANTHROPIC_API_KEY", "")
    return {
        "provider": provider,
        "name": pr["name"],
        "type": pr["type"],
        "model": (settings.get("ai_model") or "").strip() or pr["model"],
        "base_url": (settings.get("ai_base_url") or "").strip() or pr["base_url"],
        "api_key": key.strip(),
    }


def _problem(cfg):
    """还差什么才能用；能用时返回空字符串。"""
    if cfg["type"] == "none":
        return "还没有选择 AI 服务商。请到「设置 → AI 助教」里选择并填写 API Key。"
    if cfg["type"] == "anthropic" and anthropic is None:
        return "还没有安装 anthropic。请在命令行运行：pip install anthropic，然后重启软件。"
    if not cfg["api_key"]:
        return "还没有填写 API Key。请到「设置 → AI 助教」里填写。"
    if not cfg["model"]:
        return "还没有填写模型名称。请到「设置 → AI 助教」里填写。"
    if cfg["type"] == "openai" and not cfg["base_url"]:
        return "还没有填写接口地址（Base URL）。请到「设置 → AI 助教」里填写。"
    return ""


def status(settings):
    cfg = config(settings)
    problem = _problem(cfg)
    return {
        "provider": cfg["provider"],
        "provider_name": cfg["name"],
        "installed": not (cfg["type"] == "anthropic" and anthropic is None),
        "configured": not problem,
        "problem": problem,
        "model": cfg["model"],
    }


def _clip(s, n=6000):
    s = (s or "").strip()
    return s if len(s) <= n else s[:n] + "……（后文略）"


def build_request(kind, body, history):
    """把前端传来的内容组织成一次请求：返回 {messages, effort}。"""
    if kind == "essay":
        points = "\n".join(f"- {p}" for p in body.get("points") or [])
        if not points and body.get("reference"):
            # 真题没有拆好的要点，用参考答案代替
            points = "（以下为参考答案原文）\n" + _clip(body.get("reference"), 2500)
        materials = _clip(body.get("materials"), 8000)
        answer = (body.get("answer") or "").strip()
        if not answer:
            raise ValueError("请先写下你的作答再请 AI 批改")
        full = body.get("score") or 20
        content = (
            "请批改下面这道申论题的作答。\n\n"
            f"【给定资料（节选）】\n{materials}\n\n"
            f"【题目】{body.get('question')}\n"
            f"【作答要求】{body.get('requirement')}\n"
            f"【满分】{full} 分；【字数要求】{body.get('words')}\n\n"
            f"【参考要点】\n{points}\n\n"
            f"【考生作答】（共 {len(answer)} 字）\n{answer}\n\n"
            + ESSAY_RUBRIC.format(full=full)
        )
        return {"messages": [{"role": "user", "content": content}], "effort": "high"}

    if kind == "explain":
        opts = "\n".join(f"{'ABCD'[i]}. {o}" for i, o in enumerate(body.get("options") or []))
        chosen = body.get("chosen")
        chosen_txt = "ABCD"[chosen] if isinstance(chosen, int) and 0 <= chosen < 4 else "未作答"
        content = (
            f"这是一道{body.get('module')}题。\n\n"
            + (f"【材料】\n{_clip(body.get('material'), 4000)}\n\n" if body.get("material") else "")
            + f"【题目】{body.get('stem')}\n{opts}\n\n"
            f"【正确答案】{'ABCD'[int(body.get('answer', 0))]}\n"
            f"【我选的】{chosen_txt}\n"
            f"【题库解析】{body.get('explain')}\n\n"
            + (f"【我的疑问】{body.get('question')}\n\n" if body.get("question") else "")
            + "请：1) 用零基础能听懂的方式讲清这道题的解题思路；"
            "2) 如果我选错了，指出我可能错在哪；"
            "3) 总结这类题的通用方法，并出 1 道类似的练习题（附答案和解析）。"
        )
        return {"messages": [{"role": "user", "content": content}], "effort": "medium"}

    if kind == "interview":
        answer = (body.get("answer") or "").strip()
        if not answer:
            raise ValueError("请先写下你的作答要点再请 AI 点评")
        content = (
            f"这是一道结构化面试题（题型：{body.get('type')}）。\n\n"
            f"【题目】{body.get('question')}\n\n"
            f"【参考思路】{body.get('guide')}\n\n"
            f"【我的作答】\n{answer}\n\n"
            "请按面试考官的视角点评：1) 给出等级（好 / 中 / 差）和理由；"
            "2) 内容上的亮点与缺失；3) 结构和表达上的问题；"
            "4) 给出一份 3 分钟左右、口语化的示范作答。"
        )
        return {"messages": [{"role": "user", "content": content}], "effort": "medium"}

    if kind == "reader":
        sel = (body.get("text") or "").strip()
        question = (body.get("question") or "").strip() or "请讲解这段内容"
        if not sel:
            raise ValueError("先选中一段文字")
        content = (
            f"我在看公考备考资料《{body.get('title')}》"
            + (f"的“{body.get('section')}”部分" if body.get("section") else "") + "。\n\n"
            f"【我选中的内容】\n{_clip(sel, 3000)}\n\n"
            + (f"【前后文】\n{_clip(body.get('context'), 3000)}\n\n" if body.get("context") else "")
            + f"【我的问题】{question}\n\n"
            "请用通俗的话回答，紧扣公务员考试（行测、申论、面试）的考法；需要时举一个真题风格的例子。"
            "资料里有明显错误或过时的说法要指出来。"
        )
        return {"messages": [{"role": "user", "content": content}], "effort": "medium"}

    if kind == "lesson":
        question = (body.get("question") or "").strip()
        if not question:
            raise ValueError("请先写下你的问题")
        content = (
            f"我正在学习公考教程《{body.get('title')}》（{body.get('course')}）。下面是这一课的内容节选：\n\n"
            f"{_clip(body.get('text'), 6000)}\n\n"
            f"【我的问题】{question}\n\n"
            "请结合这一课的方法回答：先直接回答，再举一个公考真题风格的例子说明，最后给一条可以马上用的做题建议。"
            "不确定的事实（如具体年份的考试安排）要说明以官方公告为准。"
        )
        return {"messages": [{"role": "user", "content": content}], "effort": "medium"}

    if kind == "chat":
        msg = (body.get("message") or "").strip()
        if not msg:
            raise ValueError("请输入问题")
        messages = []
        for h in history[-16:]:
            if h["role"] in ("user", "assistant") and h["content"]:
                messages.append({"role": h["role"], "content": h["content"]})
        # 保证从 user 开始、user/assistant 交替
        while messages and messages[0]["role"] != "user":
            messages.pop(0)
        if messages and messages[-1]["role"] == "user":
            messages.pop()
        messages.append({"role": "user", "content": msg})
        return {"messages": messages, "effort": "medium"}

    if kind == "test":
        return {"messages": [{"role": "user", "content": "这是一次连接测试，请只回复：连接成功"}], "effort": "low"}

    raise ValueError("未知的 AI 功能")


def _client(cfg):
    kwargs = {"api_key": cfg["api_key"]}
    if cfg["base_url"]:
        kwargs["base_url"] = cfg["base_url"]
    return anthropic.Anthropic(**kwargs)


def _friendly(e):
    if isinstance(e, anthropic.AuthenticationError):
        return "API Key 无效，请到设置里检查。"
    if isinstance(e, anthropic.PermissionDeniedError):
        return "这个 API Key 没有调用该模型的权限。"
    if isinstance(e, anthropic.NotFoundError):
        return "找不到模型或接口地址，请检查设置里的模型名称和接口地址。"
    if isinstance(e, anthropic.RateLimitError):
        return "请求太频繁或额度已用完，请稍后再试。"
    if isinstance(e, anthropic.APIStatusError):
        return f"接口返回错误（{e.status_code}）：{e.message}"
    if isinstance(e, anthropic.APIConnectionError):
        return "连接不上 AI 接口，请检查网络或接口地址。"
    return str(e)


def _http_hint(code):
    return {
        400: "请求参数有误，请检查模型名称。",
        401: "API Key 无效，请到设置里检查。",
        402: "账户余额不足。",
        403: "这个 API Key 没有调用该模型的权限。",
        404: "找不到接口或模型，请检查设置里的接口地址和模型名称。",
        429: "请求太频繁或额度已用完，请稍后再试。",
    }.get(code, "接口返回错误。" if code < 500 else "AI 服务暂时不可用，请稍后再试。")


def stream(settings, req):
    """逐段产出回答文本。用量（tokens）写进 req["usage"]：服务商返回了就用返回的，没返回按字数估算。"""
    cfg = config(settings)
    problem = _problem(cfg)
    if problem:
        raise AIError(problem)
    usage = req.setdefault("usage", {})
    usage.update(provider=cfg["provider"], model=cfg["model"], input=0, output=0, estimated=True)
    out = []
    gen = _stream_anthropic(cfg, req) if cfg["type"] == "anthropic" else _stream_openai(cfg, req)
    for piece in gen:
        out.append(piece)
        yield piece
    if not usage.get("input") and not usage.get("output"):
        prompt = SYSTEM + "".join(m["content"] for m in req["messages"])
        usage.update(input=estimate_tokens(prompt), output=estimate_tokens("".join(out)), estimated=True)


def _openai_request(cfg, req, with_usage):
    base = cfg["base_url"].rstrip("/")
    url = base if base.endswith("/chat/completions") else base + "/chat/completions"
    body = {
        "model": cfg["model"],
        "messages": [{"role": "system", "content": SYSTEM}] + req["messages"],
        "stream": True,
    }
    if with_usage:
        body["stream_options"] = {"include_usage": True}  # 最后一段带上用量
    return urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "Authorization": f"Bearer {cfg['api_key']}",
        },
        method="POST",
    )


def _record_usage(req, u):
    if not u:
        return
    req["usage"].update(input=int(u.get("prompt_tokens") or u.get("input_tokens") or 0),
                        output=int(u.get("completion_tokens") or u.get("output_tokens") or 0), estimated=False)


def _stream_openai(cfg, req):
    try:
        try:
            resp = urllib.request.urlopen(_openai_request(cfg, req, True), timeout=TIMEOUT)  # noqa: S310
        except urllib.error.HTTPError as e:
            if e.code not in (400, 422):
                raise
            # 有的兼容接口不认识 stream_options：去掉再试一次
            resp = urllib.request.urlopen(_openai_request(cfg, req, False), timeout=TIMEOUT)  # noqa: S310
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="ignore")[:300]
        raise AIError(f"{_http_hint(e.code)}\n（HTTP {e.code}）{detail}") from e
    except urllib.error.URLError as e:
        raise AIError(f"连接不上 AI 接口，请检查网络或接口地址：{e.reason}") from e
    except (TimeoutError, OSError) as e:
        raise AIError("连接 AI 接口超时，请稍后再试。") from e

    finish = None
    try:
        with resp:
            if "json" in (resp.headers.get("Content-Type") or ""):
                # 个别服务不支持流式，直接返回了完整结果
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("error"):
                    raise AIError(f"接口返回错误：{data['error']}")
                choice = (data.get("choices") or [{}])[0]
                yield (choice.get("message") or {}).get("content") or ""
                finish = choice.get("finish_reason")
                _record_usage(req, data.get("usage"))
            else:
                for raw in resp:
                    line = raw.decode("utf-8", errors="ignore").strip()
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        obj = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    if obj.get("error"):
                        raise AIError(f"接口返回错误：{obj['error']}")
                    _record_usage(req, obj.get("usage"))
                    for ch in obj.get("choices") or []:
                        piece = (ch.get("delta") or {}).get("content")
                        if piece:
                            yield piece
                        finish = ch.get("finish_reason") or finish
    except (TimeoutError, OSError) as e:
        raise AIError("AI 接口响应超时或连接中断，请稍后再试。") from e
    except json.JSONDecodeError as e:
        raise AIError("接口返回的不是有效的 JSON，请检查接口地址是否正确。") from e
    if finish == "length":
        yield "\n\n（回答太长被截断了，可以让 AI 继续或分开提问。）"
    elif finish in ("content_filter", "sensitive"):
        yield "\n\n（回答被服务商的内容安全策略拦截了，请换个问法再试。）"


def _stream_anthropic(cfg, req):
    client = _client(cfg)
    params = {
        "model": cfg["model"],
        "max_tokens": 64000,
        "system": SYSTEM,
        "messages": req["messages"],
        "output_config": {"effort": req["effort"]},
    }
    plain = dict(params)
    plain.pop("output_config")
    attempts = [
        # 官方接口：开启拒答自动回退（被安全策略拒绝时自动换模型重试）
        lambda: client.beta.messages.stream(
            betas=["server-side-fallback-2026-07-01"], fallbacks="default", **params
        ),
        # 第三方中转接口或较旧的 SDK 可能不认识回退参数
        lambda: client.messages.stream(**params),
        lambda: client.messages.stream(**plain),
    ]
    try:
        ctx = stream_obj = None
        for i, make in enumerate(attempts):
            try:
                ctx = make()
                stream_obj = ctx.__enter__()
                break
            except (anthropic.BadRequestError, TypeError):
                if i == len(attempts) - 1:
                    raise
        try:
            for text in stream_obj.text_stream:
                yield text
            final = stream_obj.get_final_message()
            u = getattr(final, "usage", None)
            if u is not None:
                _record_usage(req, {"input_tokens": getattr(u, "input_tokens", 0),
                                    "output_tokens": getattr(u, "output_tokens", 0)})
            if final.stop_reason == "refusal":
                yield "\n\n（AI 拒绝回答了这个请求，请换个问法再试。）"
            elif final.stop_reason == "max_tokens":
                yield "\n\n（回答太长被截断了，可以让 AI 继续或分开提问。）"
        finally:
            ctx.__exit__(None, None, None)
    except anthropic.APIError as e:
        raise AIError(_friendly(e)) from e
