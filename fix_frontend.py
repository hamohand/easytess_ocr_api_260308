filepath = r'easytess-frontend\src\app\components\entity-creator.component.ts'

with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# Detect line ending style
if '\r\n' in content:
    eol = '\r\n'
    print("File uses Windows line endings (CRLF)")
else:
    eol = '\n'
    print("File uses Unix line endings (LF)")

# Find the target block
target_start = content.find("// Extraire juste le nom du fichier")
if target_start == -1:
    print("Target not found! Searching context...")
    idx = content.find('Charger l')
    while idx != -1:
        print(f"Found at {idx}: {repr(content[idx:idx+50])}")
        idx = content.find('Charger l', idx+1)
else:
    # Find the containing block start
    block_start = content.rfind("// Charger l'image de r", 0, target_start)
    block_end = content.find("                }", target_start) + len("                }")
    old_block = content[block_start:block_end]
    print("OLD BLOCK:")
    print(repr(old_block))
    print()
    
    new_block = (
        f"// Charger l'image de r\u00e9f\u00e9rence si elle existe{eol}"
        f"                if (entite.image_reference) {{{eol}"
        f"                    // Extraire le chemin relatif au dossier 'uploads/'{eol}"
        f"                    const normalized = entite.image_reference.replace(/\\\\/g, '/');\n".replace('\n', eol)
        + f"                    const uploadsIndex = normalized.indexOf('/uploads/');{eol}"
        f"                    let relativeFilename: string;{eol}"
        f"                    if (uploadsIndex !== -1) {{{eol}"
        f"                        relativeFilename = normalized.substring(uploadsIndex + '/uploads/'.length);{eol}"
        f"                    }} else {{{eol}"
        f"                        relativeFilename = normalized.split('/').pop() || normalized;{eol}"
        f"                    }}{eol}"
        f"                    const imageUrl = `http://localhost:8082/uploads/${{relativeFilename}}`;{eol}"
        f"                    this.imageUrl.set(imageUrl);{eol}"
        f"                    // Pour la d\u00e9tection, on utilise le chemin relatif au dossier uploads{eol}"
        f"                    this.uploadedImageFilename.set(relativeFilename);{eol}"
        f"{eol}"
        f"                    setTimeout(() => {{{eol}"
        f"                        this.loadImageOnCanvas(imageUrl);{eol}"
        f"                    }}, 100);{eol}"
        f"                }}"
    )
    
    content = content[:block_start] + new_block + content[block_end:]
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    print("Replacement DONE!")
    print("NEW BLOCK preview:", repr(new_block[:300]))
