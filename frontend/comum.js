// comum.js — funções compartilhadas pelas telas de meta (especies.html e clientes.html).
const BASE = "./api/v1/";
const num = (v, casas = 1) => v == null ? "–" : v.toLocaleString("pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: casas });
const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const norm = s => String(s).normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
const $ = id => document.getElementById(id);
const indices = campos => campos.reduce((o, n, i) => (o[n] = i, o), {});
const porNome = (a, b) => String(a).localeCompare(String(b), "pt-BR");

async function json(caminho) {
  const r = await fetch(BASE + caminho, { cache: "no-cache" });
  if (!r.ok) throw new Error(`${caminho}: HTTP ${r.status}`);
  return r.json();
}

function opcoes(sel, lista, atual, todos) {
  sel.innerHTML = (todos == null ? "" : `<option value="">${esc(todos)}</option>`) +
    lista.map(([v, t]) => `<option value="${esc(v)}"${String(v) === String(atual) ? " selected" : ""}>${esc(t)}</option>`).join("");
}

// Filtros no endereço (#mes=...&gc=...): o link abre a tela já filtrada.
function lerHash(chaves) {
  const p = new URLSearchParams(location.hash.slice(1));
  return Object.fromEntries(chaves.map(k => [k, p.get(k) || ""]));
}
function gravarHash(valores) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(valores)) if (v) p.set(k, v);
  history.replaceState(null, "", "#" + p.toString());
}

function pctCelula(real, meta) {
  if (meta == null) return `<span class="vazio">–</span>`;
  if (!meta) return `<span class="vazio">sem meta</span>`;
  const pct = real / meta * 100;
  return `<span class="pct">${num(pct, 1)}%<span class="barra"><i style="width:${Math.min(100, Math.max(0, pct))}%"></i></span></span>`;
}
function difCelula(real, meta) {
  if (meta == null) return `<td class="vazio">–</td>`;
  const d = real - meta;
  return `<td class="${d < 0 ? "neg" : "pos"}">${num(d, 2)}</td>`;
}

// Gerência > Supervisão > Rota: cada lista só mostra o que cabe no nível de cima. Altera `f` quando o valor some.
function hierarquiaRotas(dados, f) {
  if (!dados.gerencias.some(g => g.id === f.gc)) f.gc = "";
  opcoes($("f-gerencia"), dados.gerencias.map(g => [g.id, g.id === "--" ? g.nome : `${g.id} · ${g.nome}`]), f.gc, "Todas");
  const svs = dados.supervisoes.filter(s => !f.gc || s.gerencia === f.gc);
  if (!svs.some(s => s.id === f.sv)) f.sv = "";
  opcoes($("f-sv"), svs.map(s => [s.id, s.nome ? `${s.id} · ${s.nome}` : s.id]), f.sv, "Todas");
  const rotas = dados.rotas.filter(r => (!f.gc || r.gerencia === f.gc) && (!f.sv || r.supervisao === f.sv));
  if (!rotas.some(r => r.id === f.rota)) f.rota = "";
  opcoes($("f-rota"), rotas.map(r => [r.id, r.vendedor ? `${r.id} · ${r.vendedor}` : r.id]), f.rota, "Todas");
}

// Botão "Atualizar dados". Local (servir.py): POST /atualizar busca no Datasphere e regrava a API. No GitHub Pages
// esse endereço não existe: só relê os JSONs publicados (o workflow os atualiza de hora em hora).
function botaoAtualizar(recarregar) {
  $("atualizar").onclick = async () => {
    const botao = $("atualizar"), msg = $("atualizar-msg");
    botao.disabled = true;
    msg.textContent = "Buscando dados no Datasphere… (pode levar alguns minutos)";
    let texto;
    try {
      const r = await fetch("./atualizar", { method: "POST" });
      if ((r.headers.get("Content-Type") || "").includes("json")) {
        const res = await r.json();
        texto = res.ok ? "Dados atualizados do Datasphere." :
          `Falha ao atualizar: ${res.mensagem || (res.log || []).slice(-2).join(" ")}`;
      } else {
        texto = "No site publicado os dados são atualizados automaticamente de hora em hora. Arquivos recarregados.";
      }
    } catch {
      texto = "Sem conexão com o servidor. Arquivos recarregados.";
    }
    try { await recarregar(); } catch (erro) { falhar(erro); }
    msg.textContent = texto;
    botao.disabled = false;
  };
}

function falhar(erro) {
  $("estado").textContent = `Não foi possível ler a API (${erro.message}). Rode "python scripts/gerar.py --forcar" com dados reais.`;
}

async function carregarIndice() {
  const [esp, idx] = await Promise.all([json("especies/index.json"), json("index.json")]);
  if (idx.simulado) $("avisos").innerHTML = `<div class="aviso">A API principal está com dados SIMULADOS.</div>`;
  return { ...esp, atualizado_em: idx.atualizado_em };
}

function textoAtualizado(indice, rotulo) {
  return `${rotulo} · dados atualizados em ` +
    new Date(indice.atualizado_em).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}
