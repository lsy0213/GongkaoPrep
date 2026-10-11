#!/usr/bin/env bash
# 在 Ubuntu 服务器上装好上岸备考的服务器模式（用 root 运行；可以重复运行，做过的步骤会跳过）。
# 和 EngNest 放在同一台服务器上：共用它的 Nginx 和 Let's Encrypt 证书，Python 环境、系统用户、数据目录各管各的。
# 先把代码放到 /opt/gongkao/app、数据放到 /opt/gongkao/data（见 tools/deploy/部署说明.md），再：
#   bash /opt/gongkao/app/tools/deploy/setup.sh <公网 IP 或域名> [对外端口，默认 443]
set -euo pipefail

PUBLIC_HOST="${1:?用法：setup.sh <公网 IP 或域名> [端口]}"
PORT="${2:-443}"
ROOT=/opt/gongkao
APP=$ROOT/app
PIP_MIRROR=https://mirrors.cloud.tencent.com/pypi/simple   # 腾讯云服务器上下载 Python 包最快

echo "== 1. 系统软件"
command -v nginx >/dev/null || { apt-get update -q && DEBIAN_FRONTEND=noninteractive apt-get install -y -q nginx >/dev/null; }
dpkg -s python3-venv >/dev/null 2>&1 || DEBIAN_FRONTEND=noninteractive apt-get install -y -q python3-venv >/dev/null
[ -f /etc/nginx/ssl/engnest.crt ] || { echo "没找到 /etc/nginx/ssl/engnest.crt（和 EngNest 共用的证书），先部署 EngNest 或自己放一个证书"; exit 1; }

echo "== 2. 专门运行上岸备考的系统用户（不用 root 运行）"
id gongkao >/dev/null 2>&1 || useradd --system --home-dir $ROOT --shell /usr/sbin/nologin gongkao
mkdir -p $ROOT/data $ROOT/materials
chown -R gongkao:gongkao $ROOT/data
chmod 750 $ROOT/data
chown -R root:gongkao $ROOT/materials $APP
chmod -R u=rwX,g=rX,o= $ROOT/materials $APP   # 购买的资料和题目只给 gongkao 用户读

echo "== 3. Python 环境和依赖"
[ -x $ROOT/venv/bin/python ] || python3 -m venv $ROOT/venv
$ROOT/venv/bin/pip install -q --upgrade pip -i $PIP_MIRROR
$ROOT/venv/bin/pip install -q -r $APP/requirements-server.txt -i $PIP_MIRROR

echo "== 4. 配置和开机自启"
cat > $ROOT/gongkao.env <<EOF
GONGKAO_PUBLIC_HOSTS=$PUBLIC_HOST$([ "$PORT" = 443 ] || echo ":$PORT")
EOF
cp $APP/tools/deploy/gongkao.service /etc/systemd/system/gongkao.service
systemctl daemon-reload
systemctl enable gongkao >/dev/null
systemctl restart gongkao

echo "== 5. Nginx（HTTPS、HTTP/2、压缩；全部转给 127.0.0.1:8769）"
sed "s/__PORT__/$PORT/" $APP/tools/deploy/nginx-gongkao.conf > /etc/nginx/sites-available/gongkao
ln -sf /etc/nginx/sites-available/gongkao /etc/nginx/sites-enabled/gongkao
nginx -t -q
systemctl reload nginx
sleep 2
systemctl --no-pager --lines=0 status gongkao | head -3

echo
echo "完成。还要做的："
echo "  1) 设置登录密码（输入时不显示）："
echo "     sudo -u gongkao env GONGKAO_DATA_DIR=$ROOT/data $ROOT/venv/bin/python $APP/main.py --set-password"
echo "  2) 腾讯云控制台 → 轻量服务器 → 防火墙，确认放通了 TCP $PORT"
echo "  3) 手机浏览器打开 https://$PUBLIC_HOST$([ "$PORT" = 443 ] || echo ":$PORT")/"
