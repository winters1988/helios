"""OSINT information gathering modules."""

import socket
import ssl
import json
import re
import concurrent.futures
from datetime import datetime

import whois
import dns.resolver
import requests


def whois_lookup(domain: str) -> dict:
    """Perform WHOIS lookup on a domain."""
    try:
        w = whois.whois(domain)
        result = {}
        for key in ['domain_name', 'registrar', 'whois_server', 'creation_date',
                     'expiration_date', 'updated_date', 'name_servers',
                     'status', 'emails', 'name', 'org', 'address',
                     'city', 'state', 'country']:
            val = getattr(w, key, None)
            if val is not None:
                if isinstance(val, list):
                    val = [str(v) for v in val]
                elif isinstance(val, datetime):
                    val = val.strftime('%Y-%m-%d %H:%M:%S')
                else:
                    val = str(val)
                result[key] = val
        return {"success": True, "data": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


def dns_lookup(domain: str) -> dict:
    """Perform DNS record lookups."""
    records = {}
    record_types = ['A', 'AAAA', 'MX', 'NS', 'TXT', 'SOA', 'CNAME', 'SRV']

    for rtype in record_types:
        try:
            answers = dns.resolver.resolve(domain, rtype)
            records[rtype] = [str(rdata) for rdata in answers]
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN,
                dns.resolver.NoNameservers, dns.name.EmptyLabel):
            pass
        except Exception:
            pass

    if records:
        return {"success": True, "data": records}
    return {"success": False, "error": f"No DNS records found for {domain}"}


def reverse_dns(ip: str) -> dict:
    """Perform reverse DNS lookup."""
    try:
        hostname, _, _ = socket.gethostbyaddr(ip)
        return {"success": True, "data": {"ip": ip, "hostname": hostname}}
    except socket.herror:
        return {"success": False, "error": f"No reverse DNS entry for {ip}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def ip_geolocation(ip: str) -> dict:
    """Get IP geolocation info using ip-api.com (free, no key required)."""
    try:
        resp = requests.get(f"http://ip-api.com/json/{ip}?fields=66846719", timeout=10)
        data = resp.json()
        if data.get("status") == "success":
            return {"success": True, "data": data}
        return {"success": False, "error": data.get("message", "Lookup failed")}
    except Exception as e:
        return {"success": False, "error": str(e)}


def port_scan(target: str, ports: str = "common") -> dict:
    """Scan common ports on a target. For authorized testing only."""
    common_ports = {
        21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP", 53: "DNS",
        80: "HTTP", 110: "POP3", 143: "IMAP", 443: "HTTPS", 445: "SMB",
        993: "IMAPS", 995: "POP3S", 3306: "MySQL", 3389: "RDP",
        5432: "PostgreSQL", 5900: "VNC", 8080: "HTTP-Alt", 8443: "HTTPS-Alt"
    }

    if ports == "common":
        port_list = list(common_ports.keys())
    else:
        port_list = [int(p.strip()) for p in ports.split(",") if p.strip().isdigit()]

    try:
        ip = socket.gethostbyname(target)
    except socket.gaierror:
        return {"success": False, "error": f"Cannot resolve hostname: {target}"}

    open_ports = []

    def scan_port(port):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1.5)
            result = sock.connect_ex((ip, port))
            sock.close()
            if result == 0:
                service = common_ports.get(port, "Unknown")
                return {"port": port, "state": "open", "service": service}
        except Exception:
            pass
        return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(scan_port, p): p for p in port_list}
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result:
                open_ports.append(result)

    open_ports.sort(key=lambda x: x["port"])
    return {
        "success": True,
        "data": {
            "target": target,
            "ip": ip,
            "scanned_ports": len(port_list),
            "open_ports": open_ports
        }
    }


def http_headers(url: str) -> dict:
    """Fetch and analyze HTTP headers."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        resp = requests.head(url, timeout=10, allow_redirects=True, verify=False)
        headers = dict(resp.headers)

        security_headers = {
            "Strict-Transport-Security": headers.get("Strict-Transport-Security"),
            "Content-Security-Policy": headers.get("Content-Security-Policy"),
            "X-Frame-Options": headers.get("X-Frame-Options"),
            "X-Content-Type-Options": headers.get("X-Content-Type-Options"),
            "X-XSS-Protection": headers.get("X-XSS-Protection"),
            "Referrer-Policy": headers.get("Referrer-Policy"),
            "Permissions-Policy": headers.get("Permissions-Policy"),
        }
        missing = [k for k, v in security_headers.items() if v is None]

        return {
            "success": True,
            "data": {
                "url": resp.url,
                "status_code": resp.status_code,
                "headers": headers,
                "security_headers": {k: v for k, v in security_headers.items() if v},
                "missing_security_headers": missing,
                "server": headers.get("Server", "Not disclosed"),
                "technology": headers.get("X-Powered-By", "Not disclosed"),
            }
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def ssl_info(domain: str) -> dict:
    """Get SSL/TLS certificate information."""
    try:
        context = ssl.create_default_context()
        with socket.create_connection((domain, 443), timeout=10) as sock:
            with context.wrap_socket(sock, server_hostname=domain) as ssock:
                cert = ssock.getpeercert()

        subject = dict(x[0] for x in cert.get('subject', ()))
        issuer = dict(x[0] for x in cert.get('issuer', ()))
        san = [entry[1] for entry in cert.get('subjectAltName', ())]

        return {
            "success": True,
            "data": {
                "subject": subject,
                "issuer": issuer,
                "version": cert.get('version'),
                "serial_number": cert.get('serialNumber'),
                "not_before": cert.get('notBefore'),
                "not_after": cert.get('notAfter'),
                "subject_alt_names": san,
                "protocol": ssock.version(),
            }
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def subdomain_enum(domain: str) -> dict:
    """Enumerate subdomains using common wordlist."""
    common_subs = [
        "www", "mail", "ftp", "webmail", "smtp", "pop", "ns1", "ns2",
        "dns", "dns1", "dns2", "mx", "mx1", "mx2", "blog", "dev",
        "staging", "api", "app", "admin", "portal", "vpn", "remote",
        "test", "demo", "shop", "store", "cdn", "media", "static",
        "assets", "img", "images", "login", "auth", "sso", "git",
        "gitlab", "jenkins", "ci", "docs", "wiki", "support", "help",
        "status", "monitor", "grafana", "kibana", "elastic", "db",
        "database", "backup", "old", "new", "beta", "alpha", "m",
        "mobile", "web", "cloud", "s3", "aws", "gcp", "azure"
    ]

    found = []

    def check_subdomain(sub):
        full = f"{sub}.{domain}"
        try:
            answers = dns.resolver.resolve(full, 'A')
            ips = [str(r) for r in answers]
            return {"subdomain": full, "ips": ips}
        except Exception:
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=30) as executor:
        futures = {executor.submit(check_subdomain, s): s for s in common_subs}
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result:
                found.append(result)

    found.sort(key=lambda x: x["subdomain"])
    return {
        "success": True,
        "data": {
            "domain": domain,
            "checked": len(common_subs),
            "found": len(found),
            "subdomains": found
        }
    }


def email_harvest(domain: str) -> dict:
    """Discover possible email patterns for a domain using DNS records."""
    result = {"domain": domain, "mx_records": [], "email_patterns": [], "spf": None, "dmarc": None}

    try:
        mx = dns.resolver.resolve(domain, 'MX')
        result["mx_records"] = [{"priority": r.preference, "server": str(r.exchange)} for r in mx]
    except Exception:
        pass

    try:
        txt = dns.resolver.resolve(domain, 'TXT')
        for r in txt:
            txt_str = str(r)
            if "v=spf1" in txt_str:
                result["spf"] = txt_str
    except Exception:
        pass

    try:
        dmarc = dns.resolver.resolve(f"_dmarc.{domain}", 'TXT')
        for r in dmarc:
            result["dmarc"] = str(r)
    except Exception:
        pass

    patterns = [
        "first.last@" + domain,
        "firstlast@" + domain,
        "first_last@" + domain,
        "flast@" + domain,
        "first@" + domain,
        "f.last@" + domain,
        "last.first@" + domain,
    ]
    result["email_patterns"] = patterns

    return {"success": True, "data": result}


def technology_detect(url: str) -> dict:
    """Basic technology detection from HTTP response."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        resp = requests.get(url, timeout=10, allow_redirects=True, verify=False,
                           headers={"User-Agent": "Mozilla/5.0"})
        headers = resp.headers
        body = resp.text[:50000]

        techs = []

        header_signatures = {
            "X-Powered-By": None,
            "Server": None,
            "X-AspNet-Version": "ASP.NET",
            "X-Drupal-Cache": "Drupal",
        }
        for h, tech in header_signatures.items():
            val = headers.get(h)
            if val:
                techs.append({"name": tech or val, "source": f"Header: {h}", "detail": val})

        body_signatures = [
            (r'wp-content|wp-includes|wordpress', "WordPress"),
            (r'Drupal\.settings|drupal\.js', "Drupal"),
            (r'Joomla!?', "Joomla"),
            (r'react\.production|react-dom|__NEXT_DATA__', "React"),
            (r'ng-version|angular\.js|ng-app', "Angular"),
            (r'vue\.js|v-bind|v-model|nuxt', "Vue.js"),
            (r'jquery[\.-](\d)', "jQuery"),
            (r'bootstrap[\.-](\d)', "Bootstrap"),
            (r'cdn\.shopify\.com', "Shopify"),
            (r'squarespace\.com', "Squarespace"),
            (r'wix\.com|wixsite', "Wix"),
            (r'cloudflare', "Cloudflare"),
            (r'google-analytics|gtag|GA_TRACKING', "Google Analytics"),
            (r'googletagmanager', "Google Tag Manager"),
            (r'recaptcha', "Google reCAPTCHA"),
            (r'fonts\.googleapis\.com', "Google Fonts"),
            (r'tailwindcss|tailwind', "Tailwind CSS"),
            (r'laravel', "Laravel"),
            (r'django', "Django"),
            (r'flask', "Flask"),
            (r'express', "Express.js"),
        ]
        for pattern, tech_name in body_signatures:
            if re.search(pattern, body, re.IGNORECASE):
                techs.append({"name": tech_name, "source": "Body pattern"})

        seen = set()
        unique_techs = []
        for t in techs:
            if t["name"] not in seen:
                seen.add(t["name"])
                unique_techs.append(t)

        return {
            "success": True,
            "data": {
                "url": url,
                "technologies": unique_techs,
                "count": len(unique_techs)
            }
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
