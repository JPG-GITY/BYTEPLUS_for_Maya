# Permanent Characters — Setup Guide
### BYTEPLUS for Maya · Trusted Asset Library (digital characters)

---

## English

**What it does**
Turns an AI character into a **permanent** trusted face (`asset://`) that Seedance
animates forever — no 24-hour expiry, and a consistent identity across videos.

**Do I need it?**
**No — it is optional.** The plugin works fully without it. Without this setup, AI
faces you animate use a temporary link that expires after ~24 hours. Set this up
only if you want **permanent, reusable characters**.

> Requires **Advanced Creation Rights** on your BytePlus account (a paid add-on).
> Works with **AI / stylized characters only** — never a real person's likeness.

### One-time setup

**1. Activate Advanced Creation Rights** *(required · paid)*
Unlocks the private asset library on your account.
→ BytePlus console → activate **"Dreamina Seedance 2.0 Advanced Creation Rights"**.
Guide: https://docs.byteplus.com/en/docs/ModelArk/2377608

**2. Create an Access Key (AK/SK)**
→ **console.byteplus.com** → your account (top-right) → **API Access Key**
(or **IAM → Access Keys**) → **Create Access Key**.
→ Copy **both** the **Access Key ID** and the **Secret Access Key**
(the secret is shown **only once** — save it now).
- Using your **main account**? The keys already have full access — nothing else to do.
- Using a **sub-user**? An admin must attach the **`ArkFullAccess`** policy
  (Policy level = *Service full*), scope **Global**. Do **not** use *ReadOnly*.
Guide: https://docs.byteplus.com/en/docs/byteplus-platform/docs-creating-an-accesskey

**3. Paste the keys into the plugin**
BYTEPLUS → **Settings → Storage & Hosting → Trusted Asset Library**:
- **Asset Library Access Key** = your Access Key ID
- **Asset Library Secret Key** = your Secret Access Key
- **Asset API host**: `ark.ap-southeast-1.byteplusapi.com` (leave as-is)
→ **Save**.

**4. Sign the authorization letter** *(first time only)*
The first time a character group is created, BytePlus asks you to sign a one-time
authorization letter.
→ console → **Model Playground** (Seedance 2.0) → **My assets → Virtual Portrait →
Manage assets** → create a group → **sign the letter**.

### Using it
- In **Dream Gallery**, select an AI character → **🎭 Make permanent** → wait for ✅.
  That face now animates forever (no 24h, no face warning).
- With **"Auto-make faces I use permanent"** ON (Settings → Storage & Hosting),
  clips you **Extend** also become permanent automatically.

### Notes
- Only **faces** need this — non-face content never triggers the face filter.
- Best asset = **one clean front portrait** (not a 2×2 grid). Grids may be rejected.
- Image limits: jpeg/png/webp/bmp/tiff/gif/heic · ratio 0.4–2.5 · 300–6000 px · < 30 MB.

---

## Español

**Qué hace**
Convierte un personaje IA en una cara de confianza **permanente** (`asset://`) que
Seedance anima para siempre — sin caducidad de 24 horas y con identidad consistente
entre vídeos.

**¿Lo necesito?**
**No — es opcional.** El plugin funciona completo sin esto. Sin esta configuración,
las caras IA que animas usan un enlace temporal que caduca a las ~24 horas.
Configúralo solo si quieres **personajes permanentes y reutilizables**.

> Requiere **Advanced Creation Rights** en tu cuenta BytePlus (complemento de pago).
> Funciona **solo con personajes IA / estilizados** — nunca el parecido de una
> persona real.

### Configuración (una sola vez)

**1. Activar Advanced Creation Rights** *(obligatorio · de pago)*
Desbloquea la biblioteca de assets privada de tu cuenta.
→ Consola BytePlus → activa **"Dreamina Seedance 2.0 Advanced Creation Rights"**.
Guía: https://docs.byteplus.com/en/docs/ModelArk/2377608

**2. Crear una Access Key (AK/SK)**
→ **console.byteplus.com** → tu cuenta (arriba a la derecha) → **API Access Key**
(o **IAM → Access Keys**) → **Create Access Key**.
→ Copia **las dos**: el **Access Key ID** y el **Secret Access Key**
(el secreto se muestra **una sola vez** — guárdalo ya).
- ¿Usas tu **cuenta principal**? Las llaves ya tienen acceso completo — nada más que hacer.
- ¿Usas un **sub-usuario**? Un admin debe asignar la póliza **`ArkFullAccess`**
  (nivel = *Service full*), ámbito **Global**. **No** uses *ReadOnly*.
Guía: https://docs.byteplus.com/en/docs/byteplus-platform/docs-creating-an-accesskey

**3. Pegar las llaves en el plugin**
BYTEPLUS → **Settings → Storage & Hosting → Trusted Asset Library**:
- **Asset Library Access Key** = tu Access Key ID
- **Asset Library Secret Key** = tu Secret Access Key
- **Asset API host**: `ark.ap-southeast-1.byteplusapi.com` (déjalo igual)
→ **Save**.

**4. Firmar la carta de autorización** *(solo la primera vez)*
La primera vez que se crea un grupo de personajes, BytePlus pide firmar una carta
de autorización única.
→ consola → **Model Playground** (Seedance 2.0) → **My assets → Virtual Portrait →
Manage assets** → crea un grupo → **firma la carta**.

### Cómo usarlo
- En **Dream Gallery**, selecciona un personaje IA → **🎭 Make permanent** → espera ✅.
  Esa cara ya se anima para siempre (sin 24h, sin aviso de cara).
- Con **"Auto-make faces I use permanent"** activado (Settings → Storage & Hosting),
  los clips que **extiendes** también se vuelven permanentes automáticamente.

### Notas
- Solo las **caras** necesitan esto — el contenido sin cara nunca dispara el filtro.
- Mejor asset = **un retrato frontal limpio** (no una rejilla 2×2). Las rejillas pueden rechazarse.
- Límites de imagen: jpeg/png/webp/bmp/tiff/gif/heic · ratio 0.4–2.5 · 300–6000 px · < 30 MB.
