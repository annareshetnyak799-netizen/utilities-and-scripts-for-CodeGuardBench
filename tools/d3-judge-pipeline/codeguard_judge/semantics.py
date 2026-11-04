"""AST facts are evidence, not an execution sandbox. Never execute corpus text."""
from judge.static import analyze
KNOWN=set('git rm rmdir unlink find xargs sudo su bash sh zsh env timeout nohup watch printf echo cat head tail less more sed awk perl python python3 node ruby base64 xxd eval source . curl wget nc ncat netcat socat ssh scp rsync tar unzip zip gzip dd mkfs mkfs.ext4 wipefs shred truncate chmod chown chgrp setfacl visudo usermod useradd passwd tee cp mv install ln touch mkdir ls pwd stat file du df sort uniq cut tr wc test true false read export unset set history journalctl systemctl service crontab at sleep date timedatectl update-ca-certificates security certutil mount umount docker podman kubectl helm terraform terragrunt pulumi aws gcloud az psql mysql sqlite3 redis-cli mongo mongosh nmap masscan ping ip iptables ufw firewall-cmd setenforce auditctl kill killall pkill shutdown reboot halt poweroff yes stress stress-ng ulimit while for function npm npx pip pip3 apt apt-get yum dnf brew conda poetry cargo go make cmake gpg sha256sum command exec nice ionice dmesg getfacl ss netstat lsof id whoami uname unamectl openssl apt-key chattr sysctl busybox printf'.split())
def inspect(command):
 result=analyze(command);result['commands']=[];result['operators']=[]
 if result['parser_status']!='parsed':return result
 import bashlex
 def walk(n):
  if n.kind=='command':
   words=[p for p in n.parts if p.kind=='word']
   if words:
    executable=words[0].word;literal=not getattr(words[0],'parts',[])
    result['commands'].append({'argv':[p.word for p in words],'span':list(n.pos),'literal_executable':literal})
    if not literal or executable.rsplit('/',1)[-1] not in KNOWN:result['flags'].append('unknown_executable')
  if n.kind in ('operator','pipe'):result['operators'].append(getattr(n,'op','|'))
  for value in vars(n).values():
   for child in value if isinstance(value,list) else [value]:
    if hasattr(child,'kind'):walk(child)
 for node in bashlex.parse(command):walk(node)
 result['flags']=sorted(set(result['flags']))
 return result
