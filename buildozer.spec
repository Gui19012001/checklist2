[app]
title = APS Serra Operacao
package.name = apsserraoperacao
package.domain = br.com.ibero

source.dir = .
source.include_exts = py,png,jpg,jpeg,json,txt,env,sql
source.exclude_dirs = .git,.github,__pycache__,bin,.buildozer

# Versão de diagnóstico
version = 0.4.2

requirements = python3,kivy==2.3.1,certifi

orientation = landscape
fullscreen = 0

icon.filename = assets/icon.png
presplash.filename = assets/presplash.png

android.api = 34
android.minapi = 24
android.archs = arm64-v8a

android.accept_sdk_license = True
android.permissions = INTERNET
android.private_storage = True

android.logcat_filters = *:S python:D

p4a.bootstrap = sdl2

# A correção do charset-normalizer entrou no develop.
# Travamos exatamente no commit da correção para não pegar
# alterações futuras do develop sem controle.
p4a.branch = develop
p4a.commit = 5865575d81d53617784428ee29f57be2716311ea


[buildozer]
log_level = 2
warn_on_root = 1
