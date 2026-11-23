# PR: zerar os filtros One Euro do corpo quando a pessoa (ou um ponto) some

**Repositório:** `UnityBodyTracking` (projeto Unity)
**Data:** 2026-11-23
**Status:** PROPOSTA, ainda não implementada. Este documento descreve o problema e a mudança planejada.
**Relacionado:** [PR_one_euro_dt_pelo_horario_do_python.md](PR_one_euro_dt_pelo_horario_do_python.md), [PR_t_no_horario_da_captura.md](PR_t_no_horario_da_captura.md)

## Resumo

No `HumanoidAvatarDriver.cs`, os filtros One Euro dos 33 pontos do corpo (`poseFilters`) e da posição
horizontal do quadril (`hipXFilter`) **nunca são reiniciados**. Quando a pessoa sai do quadro e volta, o filtro
continua lembrando a posição de antes e o avatar "desliza" até a posição nova. Por alguns instantes depois disso,
o filtro também suaviza quase nada, então o avatar treme.

Os outros filtros do projeto já fazem isso certo, e esta mudança copia o padrão deles para o corpo:

| Filtro | Onde | É zerado quando some? |
|---|---|---|
| Mãos (`handFilters`) | `HumanoidAvatarDriver.ReadHands` | **sim** (`foreach (var f in handFilters[h]) f.Reset()`) |
| Cabeça (`headAcrossFilter`, `headUpFilter`) | `HumanoidAvatarDriver.SolveHead` | **sim** |
| Expressões do rosto | `AvatarFaceDriver.LateUpdate` | **sim** (`filters[i].Reset()`) |
| Pontos do corpo (`poseFilters`) | `HumanoidAvatarDriver.ReadLandmarks` | **não** |
| Quadril horizontal (`hipXFilter`) | `HumanoidAvatarDriver.ReadLandmarks` | **não** |
| Pontos do corpo no Python (`FiltroPontos`) | `rastreamento/filtros_pose.py` | sim, mas está desligado (`SUAVIZAR = False`) |

## O problema, passo a passo

Código atual (`ReadLandmarks`):

```csharp
if (receiver.HasPose)
{
    for (int i = 0; i < P.Length; i++)
        P[i] = poseFilters[i].Filter(Flip * receiver.GetWorldPosition(i), dt, minCutoff, beta);
    ...
    hipX = hipXFilter.Filter(rawHipX, dt, minCutoff, beta);
}
// sem pessoa: os filtros simplesmente não são chamados, e guardam o estado antigo
```

### Caso 1: a pessoa inteira some e volta

1. A pessoa sai da frente da webcam. O Python continua mandando pacotes com `detected = False`, ou para de mandar e o `PoseUdpReceiver` dá timeout.
2. `receiver.HasPose` fica `false`, e os filtros param de ser atualizados **com o estado antigo guardado**: a posição `x` e a velocidade `dx` de quando a pessoa saiu.
3. Enquanto isso, o avatar volta ao repouso pelos `HoldOrRelax`/`Relax` dos ossos, o que está certo.
4. A pessoa volta, em outra posição ou postura. O primeiro pacote novo passa pelo filtro como se fosse continuação do último, de segundos atrás:
   - o filtro vê um "salto" enorme num `dt` de ~33 ms e calcula uma velocidade irreal (ex.: 1 m em 33 ms = 30 m/s);
   - com `beta = 5`, o cutoff dispara, e o ponto anda ~85% do caminho no primeiro quadro e o resto nos 2 ou 3 seguintes. É o "deslize" visível;
   - a velocidade suavizada (`dx`) fica contaminada por esse pico e demora uns **0,3 a 0,5 s** para baixar (o `derivativeCutoff` é 1 Hz). Nesse tempo o cutoff fica alto e **o filtro praticamente não suaviza**, então o tremor passa direto.
5. Com `followHorizontal` ligado, o `hipXFilter` faz o mesmo com a posição lateral: o avatar desliza de onde a pessoa saiu até onde ela voltou.

### Caso 2: um ponto só some e volta (ex.: perna sai do quadro)

1. O filtro roda em **todos** os 33 pontos, mesmo nos que estão com visibilidade baixa.
2. Quando um ponto é perdido, o Python manda o valor bruto do modelo, que é ruído. Se o modelo não mandou nada, vai `0` (o `achatar` em `envio_unity.py` troca `NaN` por `0`).
3. O filtro continua "seguindo" esse lixo. Os ossos não usam o ponto nesse tempo (`Visible(...)` é falso e eles fazem `HoldOrRelax`), mas o **estado do filtro** fica errado.
4. Quando o ponto volta a ser visível, o filtro parte de uma posição sem sentido (às vezes a origem `0,0,0`). O resultado é o mesmo salto e o mesmo período de pouca suavização do caso 1, só naquele membro.

## O que vai mudar

Arquivo: `Assets/Scripts/PoseTracking/HumanoidAvatarDriver.cs`. Nenhum outro arquivo muda.

### 1. Sem pessoa: zerar todos os filtros do corpo

No `LateUpdate`, dentro do bloco que já existe para quando não há pose (`if (!hasPose) { ... }`):

```csharp
if (!hasPose)
{
    webcamHand[0] = webcamHand[1] = false;
    if (!handsEveryFrame) handValid[0] = handValid[1] = false;
    ResetBodyFilters();   // NOVO
}
```

Com um método novo:

```csharp
/// <summary>Esquece o estado dos filtros do corpo: ao reaparecer, a pessoa começa do zero (sem "deslizar").</summary>
private void ResetBodyFilters()
{
    foreach (var f in poseFilters) f.Reset();
    hipXFilter.Reset();
}
```

**Por que no `LateUpdate` e não no `ReadLandmarks`:** o `ReadLandmarks` só roda quando chega um pacote novo.
Se o Python parar de enviar (timeout), não chega pacote nenhum e o reset nunca aconteceria. O `LateUpdate` roda
todo frame, então cobre tanto o `detected = False` quanto o timeout.

O `Reset()` só desliga uma flag (`initialized = false`), então chamar isso a cada frame sem pessoa não custa nada.

### 2. Ponto com visibilidade baixa: zerar só o filtro daquele ponto

No `ReadLandmarks`, o filtro passa a rodar só nos pontos visíveis:

```csharp
for (int i = 0; i < P.Length; i++)
{
    Vector3 raw = Flip * receiver.GetWorldPosition(i);
    if (receiver.GetVisibility(i) >= minVisibility)
        P[i] = poseFilters[i].Filter(raw, dt, minCutoff, beta);
    else
    {
        poseFilters[i].Reset();   // ao voltar a ser visto, começa do zero
        P[i] = raw;               // não é usado pelos ossos (Visible() é falso)
    }
}
```

É o mesmo `minVisibility` que os ossos já usam em `Visible(...)`, então o filtro e os ossos concordam sobre quando um ponto "existe".

Os pontos que o YOLO não tem (dedos, calcanhares e pontas dos pés, que vêm com visibilidade 0 na conversão
COCO → MediaPipe) ficam sempre no valor bruto. Hoje eles já não são usados pelos ossos, então não muda nada para eles.

## Riscos a conferir na implementação

- **Código que usa `P[i]` sem checar a visibilidade.** Se algum cálculo (ex.: centro do quadril, `GroundFeet`, escala do braço) usar um ponto invisível, ele passa a receber o valor bruto em vez do suavizado. Nos dois casos é um valor sem sentido, mas o bruto pode tremer mais. É preciso procurar esses usos antes de implementar o item 2.
- **Ponto oscilando perto do `minVisibility`.** Se a visibilidade de um ponto ficar pulando em volta do limite, o filtro é zerado várias vezes e aquele ponto fica menos suavizado. O Python já segura pontos perdidos por 5 quadros (`QUADROS_TOLERANCIA`, mantendo a confiança do último valor bom), o que reduz isso. Se ainda acontecer, a saída é zerar só depois de N quadros invisíveis.
- **Modo VR (`VRAvatarRig`).** O reset afeta só os filtros dos pontos da webcam. A cabeça e as mãos do headset não passam por esses filtros, então não devem mudar. Vale testar mesmo assim.

## Como verificar

- [ ] O projeto compila no Unity.
- [ ] Sair da frente da webcam e voltar em outro lugar ou postura: o avatar vai **direto** para a pose nova, sem deslizar.
- [ ] Logo depois de voltar, parado: o avatar já fica estável, sem o meio segundo de tremor.
- [ ] Com `followHorizontal`: sair por um lado e voltar pelo outro não faz o avatar atravessar a cena deslizando.
- [ ] Tirar uma perna (ou um braço) do quadro e trazer de volta: o membro volta sem salto.
- [ ] Parar o Python com o Unity rodando e iniciar de novo: mesmo comportamento do primeiro item.
- [ ] Testar com o YOLO e com o MediaPipe.
- [ ] Modo VR (cabeça e mãos do headset): sem mudança de comportamento.

## Arquivos que serão alterados

| Arquivo | Tipo |
|---|---|
| `Assets/Scripts/PoseTracking/HumanoidAvatarDriver.cs` | alterado (`LateUpdate`, `ReadLandmarks` e método novo `ResetBodyFilters`) |
