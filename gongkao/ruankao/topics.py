"""软考·系统架构设计师的考点归类：每道综合知识题 → 模块（exam.json 的 modules）+ 考点（题型）。

先看解析开头的“本题考查××方面的知识”（出题人自己说的考点，最准），再看题干和选项的关键词。
规则按顺序匹配，先匹配到的算；都不中的落到“其他”。每个考点对应教程里讲它的那门课（课 id 前缀），
弱项诊断里点“去学”就到那门课。
"""

import re

M_HW, M_DB, M_SE, M_ARCH, M_NEW, M_SEC, M_PM, M_LAW, M_EN = (
    "计算机系统", "信息系统与数据库", "软件工程", "系统架构设计", "架构实践与新技术", "信息安全", "项目管理与数学",
    "知识产权与标准化", "专业英语")

# (考点 id, 模块, 考点名, 正则, 教程课程 id)
RULES = [
    # ---- 知识产权、标准化（关键词很独特，放前面）
    ("law-ip", M_LAW, "知识产权", r"著作权|版权|专利|商标|商业秘密|计算机软件保护条例|侵权|保护期|署名权|发表权|职务作品|委托开发|合作开发|许可使用", "rk-law"),
    ("law-std", M_LAW, "标准化", r"标准化|国家标准|行业标准|GB/T|GB\s*\d|ISO\s*\d|企业标准|地方标准|标准的(?:代号|编号|分类)", "rk-law"),
    # ---- 项目管理、数学与经济
    ("pm-schedule", M_PM, "进度管理", r"关键路径|最早(?:开始|完成)|最迟|松弛时间|总时差|自由时差|工期|网络图|甘特图|PERT|活动.{0,6}(?:持续|历时)|里程碑", "rk-pm"),
    ("pm-cost", M_PM, "成本与质量风险", r"挣值|EV\b|PV\b|AC\b|CPI|SPI|成本(?:估算|预算|控制)|风险(?:管理|识别|应对|曝光)|配置管理|基线|变更控制|质量保证|项目范围|WBS|项目管理", "rk-pm"),
    ("pm-math", M_PM, "运筹与数学", r"线性规划|运输问题|指派问题|决策(?:树|论)|乐观|悲观|后悔值|期望值|博弈|排队论|最短路径|最小生成树|最大流|概率|数学模型|动态规划|贪心|最优|利润最大|盈亏平衡|投资回收", "rk-pm"),
    # ---- 信息安全
    ("sec-crypto", M_SEC, "加密与数字签名", r"加密|解密|密钥|公钥|私钥|对称|非对称|RSA|DES|AES|SM[234]|ECC|数字签名|数字证书|消息摘要|哈希|散列|MD5|SHA|PKI|CA\b|认证中心|数字信封", "rk-sec"),
    ("sec-model", M_SEC, "安全模型与访问控制", r"BLP|Bell|Biba|Clark|Chinese\s*Wall|访问控制|自主访问|强制访问|RBAC|安全模型|安全策略|安全等级|等级保护|安全审计", "rk-sec"),
    ("sec-attack", M_SEC, "网络攻击与防御", r"攻击|病毒|木马|蠕虫|入侵检测|IDS|IPS|防火墙|DDoS|拒绝服务|SQL注入|跨站|XSS|ARP欺骗|漏洞|蜜罐|渗透|安全威胁|安全协议|SSL|TLS|IPSec|HTTPS|Kerberos|VPN", "rk-sec"),
    # ---- 系统架构设计（核心）
    ("arch-eval", M_ARCH, "架构评估", r"ATAM|SAAM|CBAM|ARID|架构评估|体系结构评估|敏感点|权衡点|风险点|非风险点|效用树|质量属性效用|基于场景的", "rk-arch"),
    ("arch-quality", M_ARCH, "质量属性与战术", r"质量属性|架构战术|设计战术|心跳|Ping|Echo|主动冗余|被动冗余|场景(?:刺激|响应)|刺激源|响应度量|(?:可用性|可修改性|性能|安全性|可测试性|易用性)(?:战术|场景|属性)", "rk-arch"),
    ("arch-style", M_ARCH, "架构风格", r"架构风格|体系结构风格|管道.{0,2}过滤器|批处理|黑板|解释器|虚拟机|仓库风格|事件驱动|隐式调用|显式调用|主程序.{0,2}子程序|面向对象风格|层次(?:式|化|结构)风格|C2|闭环|过程控制|规则系统|数据共享|独立构件|调用.{0,2}返回|进程通信|MVC|MVP|MVVM", "rk-arch"),
    ("arch-absd", M_ARCH, "ABSD 与 DSSA", r"ABSD|基于架构的软件(?:开发|设计)|DSSA|特定领域|领域分析|领域设计|领域实现|参考架构|架构需求|架构文档|架构复审|架构演化|架构实现", "rk-arch"),
    ("arch-comp", M_ARCH, "构件与中间件", r"构件|组件|中间件|EJB|COM\b|DCOM|CORBA|J2EE|Java\s*EE|\.NET|容器|ORB|IDL|消息中间件|事务中间件|应用服务器|产品线|复用|软件重用", "rk-arch"),
    ("arch-evol", M_ARCH, "架构演化与维护", r"演化|遗留系统|再工程|逆向工程|重构|集成策略|系统迁移|新旧系统|转换策略|直接转换|并行转换|分段转换", "rk-arch"),
    ("arch-rel", M_ARCH, "可靠性", r"可靠性|可靠度|失效率|MTBF|MTTF|MTTR|容错|N版本|恢复块|故障(?:树|模式)|FMEA|串联|并联|冗余设计|软件可靠性", "rk-arch"),
    ("arch-base", M_ARCH, "架构概念与视图", r"软件架构|体系结构|架构设计|4\s*\+\s*1|视图|ADL|架构描述|Kruchten|逻辑视图|进程视图|开发视图|物理视图|场景视图|架构师", "rk-arch"),
    # ---- 架构实践与新技术
    ("new-cloud", M_NEW, "云原生与微服务", r"云计算|云原生|IaaS|PaaS|SaaS|微服务|容器|Docker|Kubernetes|K8s|Serverless|无服务器|服务网格|Service\s*Mesh|DevOps|持续集成|持续交付|弹性|虚拟化", "rk-new"),
    ("new-soa", M_NEW, "SOA 与 Web 服务", r"SOA|面向服务|ESB|企业服务总线|Web\s*Service|Web服务|WSDL|SOAP|UDDI|BPEL|REST|服务注册|服务编排", "rk-new"),
    ("new-bigdata", M_NEW, "大数据架构", r"大数据|Lambda|Kappa|Hadoop|HDFS|MapReduce|Spark|Flink|Storm|数据湖|流处理|批处理层|速度层", "rk-new"),
    ("new-tech", M_NEW, "新技术", r"物联网|人工智能|机器学习|深度学习|区块链|数字孪生|边缘计算|元宇宙|5G|大模型|智能合约|共识机制|工业互联网|CPS|信息物理", "rk-new"),
    ("new-web", M_NEW, "Web 与层次式架构", r"负载均衡|反向代理|CDN|缓存|Redis|Memcache|集群|分布式|读写分离|分库分表|一致性哈希|高并发|三层|多层|表现层|业务逻辑层|数据访问层|持久层|ORM|Hibernate|MyBatis|Spring|Struts|SSH|JSP|Servlet", "rk-new"),
    # ---- 软件工程
    ("se-pattern", M_SE, "设计模式", r"设计模式|单例|工厂|抽象工厂|建造者|生成器|原型模式|适配器|桥接|组合模式|装饰|外观|享元|代理模式|责任链|命令模式|解释器模式|迭代器|中介者|备忘录|观察者|状态模式|策略模式|模板方法|访问者", "rk-se"),
    ("se-uml", M_SE, "面向对象与 UML", r"UML|用例|类图|对象图|顺序图|时序图|序列图|通信图|协作图|状态图|活动图|构件图|部署图|包图|泛化|关联|聚合|组合关系|依赖|实现关系|多态|继承|封装|面向对象", "rk-se"),
    ("se-test", M_SE, "软件测试", r"测试|白盒|黑盒|等价类|边界值|语句覆盖|判定覆盖|条件覆盖|路径覆盖|McCabe|环路复杂度|单元测试|集成测试|系统测试|验收测试|回归测试|α测试|β测试|调试", "rk-se"),
    ("se-req", M_SE, "需求工程", r"需求(?:获取|分析|定义|验证|确认|管理|跟踪|变更|规格|开发|工程)|需求说明|SRS|QFD|基本需求|期望需求|兴奋需求|功能需求|非功能需求|用户需求|业务需求", "rk-se"),
    ("se-struct", M_SE, "结构化方法", r"结构化|数据流图|DFD|数据字典|加工|E-R图|模块(?:化|独立)|耦合|内聚|扇入|扇出|结构图|IPO|PDL|判定表|判定树", "rk-se"),
    ("se-model", M_SE, "开发模型与方法", r"瀑布|螺旋|原型|增量|迭代|喷泉|V模型|快速应用开发|RAD|RUP|统一过程|敏捷|XP|极限编程|Scrum|水晶|特性驱动|净室|形式化|MDA|模型驱动|构件组装|CBSD|过程模型|生命周期", "rk-se"),
    ("se-proc", M_SE, "过程改进与维护", r"CMM|CMMI|能力成熟度|过程改进|软件维护|改正性|适应性|完善性|预防性|可维护性|软件质量|质量特性|ISO\s*9126|25010|软件度量|复杂度|代码审查|评审|走查|审查", "rk-se"),
    # ---- 信息系统与数据库
    ("db-norm", M_DB, "范式与函数依赖", r"范式|1NF|2NF|3NF|BCNF|4NF|函数依赖|候选键|候选码|主键|主码|超键|外键|无损连接|保持函数依赖|分解|闭包|Armstrong|传递依赖|部分依赖", "rk-db"),
    ("db-sql", M_DB, "关系代数与 SQL", r"关系代数|笛卡尔积|自然连接|选择运算|投影|σ|π|SQL|SELECT|GROUP\s*BY|视图|触发器|存储过程|完整性约束|参照完整性|实体完整性|索引", "rk-db"),
    ("db-tx", M_DB, "事务与并发恢复", r"事务|ACID|并发|封锁|锁|两段锁|死锁|丢失修改|脏读|不可重复读|幻读|隔离级别|日志|恢复|检查点|备份|故障恢复|undo|redo", "rk-db"),
    ("db-dist", M_DB, "分布式数据库与 NoSQL", r"分布式数据库|分片|水平分片|垂直分片|复制|CAP|BASE|最终一致性|NoSQL|MongoDB|HBase|键值|列存储|文档数据库|图数据库|主从|数据同步|两阶段提交|2PC|Paxos|Raft", "rk-db"),
    ("db-dw", M_DB, "数据仓库与数据挖掘", r"数据仓库|数据集市|OLAP|OLTP|ETL|数据挖掘|关联规则|聚类|分类算法|决策树|商业智能|BI\b|多维", "rk-db"),
    ("db-design", M_DB, "数据库设计", r"数据库设计|概念结构|逻辑结构|物理结构|E-R|实体|联系|属性|三级模式|模式|外模式|内模式|数据独立性|反规范化|冗余", "rk-db"),
    ("db-is", M_DB, "信息系统基础", r"信息系统|ERP|CRM|SCM|MRP|DSS|决策支持|电子政务|电子商务|企业信息化|业务流程|BPR|BPM|EAI|企业应用集成|战略|信息化|ITIL|数字化转型|办公自动化|专家系统|知识管理|G2B|B2C|C2C|O2O|EDI", "rk-db"),
    # ---- 计算机系统
    ("hw-os-proc", M_HW, "进程与 PV 操作", r"进程|线程|PV|P操作|V操作|信号量|互斥|同步|临界区|前趋图|管程|死锁|银行家|资源分配|调度算法|时间片|优先级|就绪|阻塞|挂起", "rk-hw"),
    ("hw-os-mem", M_HW, "存储管理与文件", r"页式|段式|段页式|页表|快表|TLB|缺页|页面置换|LRU|FIFO|OPT|虚拟存储|逻辑地址|物理地址|地址变换|文件系统|索引节点|inode|位示图|空闲块|磁盘调度|移臂|旋转调度|SSTF|SCAN|扇区|磁道|柱面", "rk-hw"),
    ("hw-embed", M_HW, "嵌入式系统", r"嵌入式|实时(?:操作)?系统|RTOS|VxWorks|μC/OS|uC/OS|BSP|板级支持|Bootloader|交叉编译|硬件抽象层|HAL|ARINC|AUTOSAR|AADL|DO-178|看门狗|中断响应|任务切换|可抢占", "rk-hw"),
    ("hw-net", M_HW, "计算机网络", r"网络|TCP|UDP|IP地址|子网|掩码|路由|OSI|协议|DNS|DHCP|HTTP|FTP|SMTP|POP3|SNMP|ARP|RARP|ICMP|以太网|交换机|路由器|VLAN|带宽|传输层|网络层|数据链路|物理层|拥塞|滑动窗口|IPv6|存储(?:网络|系统)|DAS|NAS|SAN|RAID", "rk-hw"),
    ("hw-arch", M_HW, "计算机组成", r"CPU|运算器|控制器|寄存器|程序计数器|指令|寻址|流水线|吞吐率|加速比|Cache|高速缓存|主存|内存|命中率|映射|总线|DMA|中断|I/O|输入输出|RISC|CISC|多核|多处理器|Flynn|SIMD|MIMD|存储器|ROM|RAM|Flash", "rk-hw"),
    ("hw-perf", M_HW, "系统性能评价", r"性能评价|基准测试|MIPS|MFLOPS|CPI|主频|响应时间|吞吐量|TPC|SPEC|负载|性能指标|Amdahl|阿姆达尔|系统配置", "rk-hw"),
    ("hw-num", M_HW, "数制与校验码", r"进制|补码|原码|反码|移码|浮点数|定点数|阶码|尾数|校验码|海明码|汉明码|CRC|奇偶校验|循环冗余", "rk-hw"),
]

_COMPILED = [(tid, mod, name, re.compile(rx, re.I), cid) for tid, mod, name, rx, cid in RULES]
TOPICS = {tid: {"id": tid, "module": mod, "name": name, "course": cid} for tid, mod, name, _rx, cid in _COMPILED}
for _m, _cid in ((M_HW, "rk-hw"), (M_DB, "rk-db"), (M_SE, "rk-se"), (M_ARCH, "rk-arch"), (M_NEW, "rk-new"), (M_SEC, "rk-sec"),
                 (M_PM, "rk-pm"), (M_LAW, "rk-law"), (M_EN, "rk-law")):
    TOPICS.setdefault(f"{_cid}-other-{_m}", {"id": f"{_cid}-other-{_m}", "module": _m, "name": f"{_m}·其他", "course": _cid})
TOPICS["en"] = {"id": "en", "module": M_EN, "name": "专业英语", "course": "rk-law"}

NAME2ID = {t["name"]: tid for tid, t in TOPICS.items()}

HEAD_RE = re.compile(r"本题(?:主要)?考查(?:的是|了)?(.{2,40}?)(?:方面|的基础|的基本|相关|知识|概念|。|，)")
EN_RE = re.compile(r"[A-Za-z]{3,}(?:\s+[A-Za-z]{2,}){6,}")


def classify_text(stem, options=None, explain="", num=0):
    """→ (模块, 考点 id)。"""
    opts = " ".join(o for o in (options or []) if o)
    if (num >= 71 and EN_RE.search(stem or "")) or (EN_RE.search(stem or "") and not re.search(r"[一-鿿]{6,}", stem or "")):
        return M_EN, "en"
    head = HEAD_RE.search(explain or "")
    probes = ([head.group(1)] if head else []) + [(stem or "") + " " + opts, (explain or "")[:300]]
    for probe in probes:
        for tid, mod, _name, rx, _cid in _COMPILED:
            if rx.search(probe):
                return mod, tid
    return M_ARCH, "rk-arch-other-系统架构设计"


def classify(module, sub, stem, options):
    """qdb.Bank 用的考点归类（签名和公考的 topics.classify 一样）：题库里已经存了考点 id（sub 字段）就直接用。"""
    if sub and sub in TOPICS:
        return sub
    if sub and sub in NAME2ID:
        return NAME2ID[sub]
    return classify_text(stem, options)[1]


COURSE_TITLES = {"rk-hw": "计算机系统", "rk-db": "信息系统与数据库", "rk-se": "软件工程", "rk-arch": "系统架构设计",
                 "rk-new": "架构实践", "rk-sec": "信息安全", "rk-pm": "项目管理 · 数学与经济", "rk-law": "知识产权 · 标准化 · 英语"}


def all_topics():
    """和公考 topics.all_topics 一样的格式：lesson 是教程里讲它的课程（#/learn/<id>）。"""
    out = []
    for tid, t in TOPICS.items():
        out.append({"id": tid, "module": t["module"], "name": t["name"], "lesson": t["course"],
                    "lesson_title": COURSE_TITLES.get(t["course"], "")})
    return out


def topic_name(tid):
    t = TOPICS.get(tid)
    return t["name"] if t else tid
