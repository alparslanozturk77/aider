"""Plan modu: önce araştır ve plan sun, onay alınca uygula."""

from .tools import Tool

PLAN_MODE_REMINDER = """
ŞU AN PLAN MODUNDASIN.

Bu modda salt-okunur araçları (Read, Grep, Glob, Skill) serbestçe kullanabilirsin.
Dosya değiştiren ya da komut çalıştıran araçlar (Write, Edit, Bash) BLOKLUDUR.

Görevin: kod tabanını araştır, sonra ne yapacağını anlatan somut bir plan yaz ve
ExitPlanMode ile kullanıcıya sun. Kullanıcı onaylamadan hiçbir değişiklik yapma.
"""


class ExitPlanModeTool(Tool):
    name = "ExitPlanMode"
    description = (
        "Hazırladığın uygulama planını kullanıcıya onaya sunar. Yalnızca kod yazmayı "
        "gerektiren işlerde ve araştırmanı BİTİRDİKTEN sonra çağır. Sadece soru "
        "yanıtlıyorsan ya da araştırma yapıyorsan çağırma."
    )
    parameters = {
        "type": "object",
        "properties": {
            "plan": {
                "type": "string",
                "description": "Uygulanacak adımların markdown planı; kısa ve somut tut",
            }
        },
        "required": ["plan"],
    }

    def run(self, ctx, plan):
        ctx.io.tool_output("\n" + plan + "\n")
        if ctx.io.confirm_ask("Bu planla devam edilsin mi?"):
            ctx.plan_mode = False
            ctx.approved_plan = plan
            return (
                "Kullanıcı planı onayladı. Plan modu kapandı; artık Write, Edit ve Bash "
                "kullanabilirsin. Planı uygulamaya başla."
            )
        return (
            "Kullanıcı planı onaylamadı. Plan modunda kal, ne değiştirmek istediğini "
            "sor ve planı ona göre yenile."
        )
