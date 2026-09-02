[app]
title = APS Serra Operacao
package.name = apsserraoperacao
package.domain = br.com.ibero

source.dir = .
source.include_exts = py,png,jpg,jpeg,json,txt,env,sql
source.exclude_dirs = .git,.github,__pycache__,bin,.buildozer

version = 0.4.0

requirements = python3,kivy==2.3.1

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
p4a.branch = develop


[buildozer]
log_level = 2
warn_on_root = 1
