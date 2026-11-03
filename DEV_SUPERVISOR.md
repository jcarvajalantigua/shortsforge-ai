# Pendiente sin resolver — shortsforge-ai

Pendiente: ruff check en rojo

Detalle:
```
vider"] = "pyttsx3"
185 |         except Exception as e:
    |                ^^^^^^^^^
186 |             manifest["pyttsx3_error"] = str(e)
187 |     # 4) espeak
    |

BLE001 Do not catch blind exception: `Exception`
   --> tools/tts_generator.py:198:20
    |
196 |                 manifest["provider"] = exe
197 |                 manifest["out"] = str(out.with_suffix(".wav"))
198 |             except Exception as e:
    |                    ^^^^^^^^^
199 |                 manifest["espeak_error"] = str(e)
200 |     # 5) fallback silencioso documentado
    |

EXE001 Shebang is present but file is not executable
 --> tools/uploader.py:1:1
  |
1 | #!/usr/bin/env python3
  | ^^^^^^^^^^^^^^^^^^^^^^
2 | """
3 | uploader.py — Subida vía YouTube Data API v3 con el OAuth DEL DUEÑO.
  |

EXE001 Shebang is present but file is not executable
 --> tools/video_assembler.py:1:1
  |
1 | #!/usr/bin/env python3
  | ^^^^^^^^^^^^^^^^^^^^^^
2 | """
3 | video_assembler.py — Short vertical 1080x1920, formato ESTÁNDAR (layout v2).
  |

BLE001 Do not catch blind exception: `Exception`
  --> tools/video_assembler.py:63:12
   |
61 |     try:
62 |         result.update(render_core.render(script, images, args.audio, Path(args.out)))
63 |     except Exception as e:
   |            ^^^^^^^^^
64 |         result["error"] = str(e)
65 |         print(json.dumps(result, ensure_ascii=False, indent=2))
   |

Found 108 errors.
No fixes available (10 hidden fixes can be enabled with the `--unsafe-fixes` option).

```

Bonsai (2 intentos) y Claude Code no generaron un fix valido.
Ruta manual: abrir el repo en VSCode Insiders o correr `claude` en el directorio y resolver.
NO mergear a main sin OK del dueno.
