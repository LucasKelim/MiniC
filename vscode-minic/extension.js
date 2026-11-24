const vscode = require("vscode");
const { spawn } = require("child_process");
const path = require("path");

const COMPILER_ROOT = path.resolve(__dirname, "..");

const CHECK_SCRIPT = `
import json, sys
sys.path.insert(0, ${JSON.stringify(COMPILER_ROOT)})
from compiler.diagnostics import ErrorReporter
from compiler.lexer import Lexer
from compiler.parser import Parser
from compiler.semantic import SemanticAnalyzer

code = sys.stdin.read()
rep = ErrorReporter(code)
tokens = Lexer(code, rep).tokenize()
ast = Parser(tokens, rep).parse()
if not rep.has_errors():
    SemanticAnalyzer(rep).analyze(ast)

out = [
    {"phase": e.phase, "message": e.message, "line": e.line, "column": e.column}
    for e in rep.errors
]
print(json.dumps(out))
`;

/**
 * Calcula o intervalo (Range) do token ou caractere na linha onde ocorreu o erro.
 */
function computeDiagnosticRange(doc, line1Based, col1Based) {
  const lineIdx = Math.max(0, Math.min(doc.lineCount - 1, line1Based - 1));
  const lineText = doc.lineAt(lineIdx).text;
  const startCol = Math.max(0, Math.min(lineText.length, col1Based - 1));

  // Destaca a palavra/token a partir da coluna do erro
  const rest = lineText.slice(startCol);
  const tokenMatch = rest.match(/^([A-Za-z0-9_.]+|==|!=|<=|>=|&&|\|\||"[^"]*"|\S)/);
  const length = tokenMatch ? tokenMatch[0].length : 1;
  const endCol = Math.min(lineText.length, startCol + Math.max(1, length));

  return new vscode.Range(lineIdx, startCol, lineIdx, endCol);
}

function validateDocument(doc, collection) {
  if (!doc || doc.languageId !== "minic") {
    return;
  }

  const proc = spawn("python3", ["-c", CHECK_SCRIPT], {
    cwd: COMPILER_ROOT,
  });

  let stdout = "";
  let stderr = "";

  proc.stdout.on("data", (chunk) => {
    stdout += chunk.toString();
  });

  proc.stderr.on("data", (chunk) => {
    stderr += chunk.toString();
  });

  proc.on("close", (code) => {
    if (code !== 0 || !stdout.trim()) {
      return;
    }
    try {
      const errors = JSON.parse(stdout);
      const diagnostics = errors.map((err) => {
        const range = computeDiagnosticRange(doc, err.line, err.column);
        const diag = new vscode.Diagnostic(
          range,
          `[${err.phase}] ${err.message}`,
          vscode.DiagnosticSeverity.Error
        );
        diag.source = `MiniC (${err.phase})`;
        return diag;
      });
      collection.set(doc.uri, diagnostics);
    } catch (_e) {
      // Ignora erro de parse JSON inesperado
    }
  });

  proc.stdin.write(doc.getText());
  proc.stdin.end();
}

// ============================================================================
// Indexador leve de símbolos (Classes, Campos, Métodos, Funções e Variáveis)
// ============================================================================

function findMatchingBrace(text, openIdx) {
  let depth = 0;
  let inStr = false;
  for (let i = openIdx; i < text.length; i++) {
    const ch = text[i];
    if (ch === '"' && text[i - 1] !== "\\") {
      inStr = !inStr;
      continue;
    }
    if (inStr) continue;
    if (ch === "/" && text[i + 1] === "/") {
      while (i < text.length && text[i] !== "\n") i++;
      continue;
    }
    if (ch === "/" && text[i + 1] === "*") {
      i += 2;
      while (i < text.length && !(text[i] === "*" && text[i + 1] === "/")) i++;
      i++;
      continue;
    }
    if (ch === "{") depth++;
    else if (ch === "}") {
      depth--;
      if (depth === 0) return i;
    }
  }
  return text.length - 1;
}

function indexDocument(doc) {
  const text = doc.getText();
  const classes = new Map();   // name -> { name, pos, startOffset, endOffset, fields, methods, constructor }
  const functions = new Map(); // name -> { name, returnType, params, pos }
  const varTypes = new Map();  // varName -> typeName

  // 1. Classes e seus membros
  const classRe = /\bclass\s+([A-Za-z_][A-Za-z0-9_]*)\s*\{/g;
  let m;
  while ((m = classRe.exec(text)) !== null) {
    const clsName = m[1];
    const nameOffset = m.index + m[0].indexOf(clsName);
    const openBrace = m.index + m[0].length - 1;
    const closeBrace = findMatchingBrace(text, openBrace);
    const body = text.slice(openBrace + 1, closeBrace);
    const bodyBase = openBrace + 1;

    const clsInfo = {
      name: clsName,
      pos: doc.positionAt(nameOffset),
      startOffset: m.index,
      endOffset: closeBrace,
      fields: [],
      methods: [],
      constructor: null,
    };

    // Percorre apenas o nível superior do corpo da classe (depth === 0)
    let depth = 0;
    let stmtStart = 0;
    for (let i = 0; i < body.length; i++) {
      const ch = body[i];
      if (ch === "{") {
        if (depth === 0) {
          const header = body.slice(stmtStart, i).trim();
          const headerAbsStart = bodyBase + stmtStart + body.slice(stmtStart, i).indexOf(header);
          // Construtor: [public|private] ClassName(params)
          const ctorMatch = header.match(/^(?:(public|private)\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)$/);
          if (ctorMatch && ctorMatch[2] === clsName) {
            const access = ctorMatch[1] || "public";
            const params = ctorMatch[3].trim();
            const nameIdx = header.indexOf(clsName);
            clsInfo.constructor = {
              name: clsName,
              access,
              params,
              pos: doc.positionAt(headerAbsStart + Math.max(0, nameIdx)),
            };
          } else {
            // Método: [public|private] retType methodName(params)
            const methMatch = header.match(
              /^(?:(public|private)\s+)?([A-Za-z_][A-Za-z0-9_]*)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)$/
            );
            if (methMatch) {
              const access = methMatch[1] || "public";
              const returnType = methMatch[2];
              const methName = methMatch[3];
              const params = methMatch[4].trim();
              const nameIdx = header.indexOf(methName, header.indexOf(returnType) + returnType.length);
              clsInfo.methods.push({
                name: methName,
                returnType,
                params,
                access,
                pos: doc.positionAt(headerAbsStart + Math.max(0, nameIdx)),
              });
            }
          }
        }
        depth++;
      } else if (ch === "}") {
        depth--;
        if (depth === 0) {
          stmtStart = i + 1;
        }
      } else if (ch === ";" && depth === 0) {
        const decl = body.slice(stmtStart, i).trim();
        const fieldMatch = decl.match(
          /^(?:(public|private)\s+)?([A-Za-z_][A-Za-z0-9_]*)\s+([A-Za-z_][A-Za-z0-9_]*)$/
        );
        if (fieldMatch) {
          const access = fieldMatch[1] || "public";
          const fieldType = fieldMatch[2];
          const fieldName = fieldMatch[3];
          const declAbsStart = bodyBase + stmtStart + body.slice(stmtStart, i).indexOf(decl);
          const nameIdx = decl.lastIndexOf(fieldName);
          clsInfo.fields.push({
            name: fieldName,
            type: fieldType,
            access,
            pos: doc.positionAt(declAbsStart + Math.max(0, nameIdx)),
          });
        }
        stmtStart = i + 1;
      }
    }

    classes.set(clsName, clsInfo);
  }

  // 2. Funções globais (fora de classes)
  const funcRe = /\b([A-Za-z_][A-Za-z0-9_]*)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)\s*\{/g;
  const reserved = new Set(["if", "while", "for", "return", "new", "class", "public", "private", "else"]);
  while ((m = funcRe.exec(text)) !== null) {
    const insideClass = Array.from(classes.values()).some(
      (c) => m.index >= c.startOffset && m.index <= c.endOffset
    );
    if (insideClass) continue;
    const returnType = m[1];
    const fnName = m[2];
    const params = m[3].trim();
    if (reserved.has(returnType) || reserved.has(fnName)) continue;
    const nameOffset = m.index + m[0].indexOf(fnName, returnType.length);
    functions.set(fnName, {
      name: fnName,
      returnType,
      params,
      pos: doc.positionAt(nameOffset),
    });
  }

  // 3. Variáveis e parâmetros tipados (ex: ContaBancaria c1 = ..., Ponto p)
  const varRe = /\b([A-Za-z_][A-Za-z0-9_]*)\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?=[=,;)])/g;
  while ((m = varRe.exec(text)) !== null) {
    const typeName = m[1];
    const varName = m[2];
    if (reserved.has(typeName) || reserved.has(varName)) continue;
    if (classes.has(typeName) || ["int", "float", "bool", "string"].includes(typeName)) {
      varTypes.set(varName, typeName);
    }
  }

  return { classes, functions, varTypes };
}

function getEnclosingClass(index, offset) {
  for (const cls of index.classes.values()) {
    if (offset >= cls.startOffset && offset <= cls.endOffset) {
      return cls;
    }
  }
  return null;
}

function resolveMemberContext(doc, position, index) {
  const lineText = doc.lineAt(position.line).text;
  const wordRange = doc.getWordRangeAtPosition(position, /[A-Za-z_][A-Za-z0-9_]*/);
  if (!wordRange) return null;
  const word = doc.getText(wordRange);
  const beforeWord = lineText.slice(0, wordRange.start.character);
  const dotMatch = beforeWord.match(/([A-Za-z_][A-Za-z0-9_]*)\s*\.\s*$/);
  if (!dotMatch) return { word, targetClass: null, isMember: false };

  const receiver = dotMatch[1];
  const offset = doc.offsetAt(position);
  let targetClassName = null;
  if (receiver === "this") {
    const enc = getEnclosingClass(index, offset);
    if (enc) targetClassName = enc.name;
  } else {
    targetClassName = index.varTypes.get(receiver) || null;
  }
  const targetClass = targetClassName ? index.classes.get(targetClassName) || null : null;
  return { word, targetClass, isMember: true, receiver };
}

function activate(context) {
  const diagnostics = vscode.languages.createDiagnosticCollection("minic");
  context.subscriptions.push(diagnostics);

  let timer = null;
  const triggerValidate = (doc) => {
    if (!doc || doc.languageId !== "minic") return;
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => validateDocument(doc, diagnostics), 150);
  };

  // Valida o arquivo aberto atualmente
  if (vscode.window.activeTextEditor) {
    validateDocument(vscode.window.activeTextEditor.document, diagnostics);
  }

  context.subscriptions.push(
    vscode.window.onDidChangeActiveTextEditor((editor) => {
      if (editor) validateDocument(editor.document, diagnostics);
    }),
    vscode.workspace.onDidOpenTextDocument((doc) => validateDocument(doc, diagnostics)),
    vscode.workspace.onDidSaveTextDocument((doc) => validateDocument(doc, diagnostics)),
    vscode.workspace.onDidChangeTextDocument((event) => triggerValidate(event.document)),
    vscode.workspace.onDidCloseTextDocument((doc) => diagnostics.delete(doc.uri))
  );

  // 1. Autocomplete após 'this.' e 'obj.'
  const completionProvider = vscode.languages.registerCompletionItemProvider(
    "minic",
    {
      provideCompletionItems(doc, position) {
        const linePrefix = doc.lineAt(position).text.slice(0, position.character);
        const dotMatch = linePrefix.match(/([A-Za-z_][A-Za-z0-9_]*)\.\s*[A-Za-z0-9_]*$/);
        if (!dotMatch) return undefined;

        const receiver = dotMatch[1];
        const index = indexDocument(doc);
        const offset = doc.offsetAt(position);
        const enclosing = getEnclosingClass(index, offset);

        let targetClass = null;
        let allowPrivate = false;

        if (receiver === "this") {
          targetClass = enclosing;
          allowPrivate = true;
        } else {
          const typeName = index.varTypes.get(receiver);
          if (typeName && index.classes.has(typeName)) {
            targetClass = index.classes.get(typeName);
            allowPrivate = enclosing !== null && enclosing.name === targetClass.name;
          }
        }

        if (!targetClass) return undefined;

        const items = [];
        for (const f of targetClass.fields) {
          if (f.access === "private" && !allowPrivate) continue;
          const item = new vscode.CompletionItem(f.name, vscode.CompletionItemKind.Field);
          item.detail = `${f.access} ${f.type} ${targetClass.name}.${f.name}`;
          items.push(item);
        }
        for (const meth of targetClass.methods) {
          if (meth.access === "private" && !allowPrivate) continue;
          const item = new vscode.CompletionItem(meth.name, vscode.CompletionItemKind.Method);
          item.detail = `${meth.access} ${meth.returnType} ${meth.name}(${meth.params})`;
          item.insertText = meth.params
            ? new vscode.SnippetString(`${meth.name}($0)`)
            : new vscode.SnippetString(`${meth.name}()`);
          items.push(item);
        }
        return items;
      },
    },
    "."
  );

  // 2. Go to Definition (Cmd+Click / F12) em classes, métodos, campos e funções
  const definitionProvider = vscode.languages.registerDefinitionProvider("minic", {
    provideDefinition(doc, position) {
      const index = indexDocument(doc);
      const ctx = resolveMemberContext(doc, position, index);
      if (!ctx) return undefined;

      if (ctx.isMember && ctx.targetClass) {
        const field = ctx.targetClass.fields.find((f) => f.name === ctx.word);
        if (field) return new vscode.Location(doc.uri, field.pos);
        const meth = ctx.targetClass.methods.find((m) => m.name === ctx.word);
        if (meth) return new vscode.Location(doc.uri, meth.pos);
      }

      if (index.classes.has(ctx.word)) {
        return new vscode.Location(doc.uri, index.classes.get(ctx.word).pos);
      }

      if (index.functions.has(ctx.word)) {
        return new vscode.Location(doc.uri, index.functions.get(ctx.word).pos);
      }

      return undefined;
    },
  });

  // 3. Hover (passar o mouse) mostrando parâmetros, tipos e assinatura
  const hoverProvider = vscode.languages.registerHoverProvider("minic", {
    provideHover(doc, position) {
      const index = indexDocument(doc);
      const ctx = resolveMemberContext(doc, position, index);
      if (!ctx) return undefined;

      if (ctx.isMember && ctx.targetClass) {
        const meth = ctx.targetClass.methods.find((m) => m.name === ctx.word);
        if (meth) {
          const md = new vscode.MarkdownString();
          md.appendCodeblock(
            `${meth.access} ${meth.returnType} ${ctx.targetClass.name}.${meth.name}(${meth.params})`,
            "minic"
          );
          return new vscode.Hover(md);
        }
        const field = ctx.targetClass.fields.find((f) => f.name === ctx.word);
        if (field) {
          const md = new vscode.MarkdownString();
          md.appendCodeblock(`${field.access} ${field.type} ${ctx.targetClass.name}.${field.name}`, "minic");
          return new vscode.Hover(md);
        }
      }

      if (index.classes.has(ctx.word)) {
        const cls = index.classes.get(ctx.word);
        const lines = [`class ${cls.name}`];
        if (cls.constructor) {
          lines.push(`  ${cls.constructor.access} ${cls.name}(${cls.constructor.params})`);
        }
        const md = new vscode.MarkdownString();
        md.appendCodeblock(lines.join("\n"), "minic");
        return new vscode.Hover(md);
      }

      if (index.functions.has(ctx.word)) {
        const fn = index.functions.get(ctx.word);
        const md = new vscode.MarkdownString();
        md.appendCodeblock(`${fn.returnType} ${fn.name}(${fn.params})`, "minic");
        return new vscode.Hover(md);
      }

      return undefined;
    },
  });

  context.subscriptions.push(completionProvider, definitionProvider, hoverProvider);

  // Comando para compilar e executar o arquivo .mc atual no terminal integrado
  const runCmd = vscode.commands.registerCommand("minic.runFile", async () => {
    const editor = vscode.window.activeTextEditor;
    if (!editor || editor.document.languageId !== "minic") {
      vscode.window.showWarningMessage("Abra um arquivo .mc para executar com o MiniC.");
      return;
    }
    await editor.document.save();
    const filePath = editor.document.fileName;
    const mainPy = path.join(COMPILER_ROOT, "main.py");

    let term = vscode.window.terminals.find((t) => t.name === "MiniC");
    if (!term) {
      term = vscode.window.createTerminal({ name: "MiniC", cwd: COMPILER_ROOT });
    }
    term.show();
    term.sendText(`python3 "${mainPy}" "${filePath}" --all-targets --run`);
  });

  context.subscriptions.push(runCmd);
}

function deactivate() {}

module.exports = { activate, deactivate };
