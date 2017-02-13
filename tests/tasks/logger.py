from mrq.task import Task
from mrq.context import log
import sys
PY3 = sys.version_info > (3,)


class Simple(Task):

    def run(self, params):


        # Some systems may be configured like this.
        if not PY3 and params.get("utf8_sys_stdout"):
            import codecs
            import sys
            UTF8Writer = codecs.getwriter('utf8')
            sys.stdout = UTF8Writer(sys.stdout)
        if params["class_name"] == "unicode":
            log.info(u"caf\xe9")
        elif params["class_name"] == "string":
            log.info("cafe")
        elif params["class_name"] == "latin-1":
            log.info("caf\xe9")
        elif params["class_name"] == "bytes1":
            log.info("Mat\xc3\xa9riels d'entra\xc3\xaenement")

        return True
