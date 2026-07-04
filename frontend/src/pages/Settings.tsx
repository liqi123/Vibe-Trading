import i18n from "@/i18n";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Database, KeyRound, Loader2, RotateCcw, Save, Server, SlidersHorizontal } from "lucide-react";
import { toast } from "sonner";
import { api, isAuthRequiredError, type DataSourceSettings, type LLMProviderOption, type LLMSettings } from "@/lib/api";
import { getApiAuthKey, setApiAuthKey } from "@/lib/apiAuth";

interface LLMFormState {
  provider: string;
  model_name: string;
  base_url: string;
  temperature: number;
  timeout_seconds: number;
  max_retries: number;
  reasoning_effort: string;
}

const fieldClass =
  "w-full rounded-md border bg-background px-3 py-2 text-sm outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/20 disabled:cursor-not-allowed disabled:opacity-60";
const labelClass = "text-sm font-medium";
const hintClass = "text-xs text-muted-foreground";

function toForm(settings: LLMSettings): LLMFormState {
  return {
    provider: settings.provider,
    model_name: settings.model_name,
    base_url: settings.base_url,
    temperature: settings.temperature,
    timeout_seconds: settings.timeout_seconds,
    max_retries: settings.max_retries,
    reasoning_effort: settings.reasoning_effort || "",
  };
}

export function Settings() {
  const [settings, setSettings] = useState<LLMSettings | null>(null);
  const [dataSettings, setDataSettings] = useState<DataSourceSettings | null>(null);
  const [form, setForm] = useState<LLMFormState | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [localApiKey, setLocalApiKeyState] = useState(() => getApiAuthKey());
  const [clearApiKey, setClearApiKey] = useState(false);
  const [tushareToken, setTushareToken] = useState("");
  const [clearTushareToken, setClearTushareToken] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [dataSaving, setDataSaving] = useState(false);
  const [settingsLoadError, setSettingsLoadError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;

    Promise.allSettled([
      api.getLLMSettings(),
      api.getDataSourceSettings(),
    ])
      .then(([llmResult, dataSourceResult]) => {
        if (!alive) return;

        if (llmResult.status === "fulfilled") {
          setSettings(llmResult.value);
          setForm(toForm(llmResult.value));
        } else {
          const message = llmResult.reason instanceof Error ? llmResult.reason.message : "Unknown error";
          setSettingsLoadError(message);
          if (isAuthRequiredError(llmResult.reason)) {
            toast.error(message);
          } else {
            toast.error(`加载LLM设置失败: ${message}`);
          }
        }

        if (dataSourceResult.status === "fulfilled") {
          setDataSettings(dataSourceResult.value);
        } else {
          const message = dataSourceResult.reason instanceof Error ? dataSourceResult.reason.message : "Unknown error";
          setSettingsLoadError(message);
          if (isAuthRequiredError(dataSourceResult.reason)) {
            toast.error(message);
          } else {
            toast.error(`加载数据源设置失败: ${message}`);
          }
        }
      })
      .finally(() => {
        if (alive) setLoading(false);
      });

    return () => {
      alive = false;
    };
  }, []);

  const providers = settings?.providers ?? [];
  const selectedProvider = useMemo<LLMProviderOption | undefined>(
    () => providers.find((provider) => provider.name === form?.provider),
    [form?.provider, providers],
  );

  const applyProviderDefaults = (provider = selectedProvider) => {
    if (!provider || !form) return;
    setForm({
      ...form,
      model_name: provider.default_model,
      base_url: provider.default_base_url,
    });
  };

  const onProviderChange = (name: string) => {
    const provider = providers.find((item) => item.name === name);
    if (!provider || !form) return;
    setForm({
      ...form,
      provider: provider.name,
      model_name: provider.default_model,
      base_url: provider.default_base_url,
    });
    setApiKey("");
    setClearApiKey(false);
  };

  const submitLocalApiKey = (event: FormEvent) => {
    event.preventDefault();
    setApiAuthKey(localApiKey);
    toast.success("本地API密钥已保存");
    window.location.reload();
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!form) return;
    setSaving(true);
    try {
      const updated = await api.updateLLMSettings({
        ...form,
        api_key: apiKey.trim() || undefined,
        clear_api_key: clearApiKey,
      });
      setSettings(updated);
      setForm(toForm(updated));
      setApiKey("");
      setClearApiKey(false);
      toast.success("LLM设置已保存");
    } catch (error) {
      toast.error(`保存LLM设置失败: ${error instanceof Error ? error.message : "未知错误"}`);
    } finally {
      setSaving(false);
    }
  };

  const submitDataSources = async (event: FormEvent) => {
    event.preventDefault();
    setDataSaving(true);
    try {
      const updated = await api.updateDataSourceSettings({
        tushare_token: tushareToken.trim() || undefined,
        clear_tushare_token: clearTushareToken,
      });
      setDataSettings(updated);
      setTushareToken("");
      setClearTushareToken(false);
      toast.success("数据源设置已保存");
    } catch (error) {
      toast.error(`保存数据源设置失败: ${error instanceof Error ? error.message : "未知错误"}`);
    } finally {
      setDataSaving(false);
    }
  };

  const localApiAccessSection = (
    <form onSubmit={submitLocalApiKey} className="rounded-lg border bg-card p-5 shadow-sm">
      <div className="mb-4 space-y-1">
        <div className="flex items-center gap-2">
          <KeyRound className="h-4 w-4 text-primary" />
          <h2 className="text-base font-semibold">本地API访问</h2>
        </div>
        <p className="text-sm text-muted-foreground">远程或私有部署时，在浏览器中输入服务器API密钥。本地使用可留空。</p>
      </div>
      <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto]">
        <label className="grid gap-2">
          <span className={labelClass}>服务器API密钥</span>
          <input
            type="password"
            value={localApiKey}
            onChange={(event) => setLocalApiKeyState(event.target.value)}
            className={fieldClass}
            placeholder="仅存储在本浏览器中。留空则清除。"
            autoComplete="current-password"
          />
        </label>
        <button
          type="submit"
          className="inline-flex items-center justify-center gap-2 self-end rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition hover:opacity-90"
        >
          <Save className="h-4 w-4" />
          保存
        </button>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">仅存储在本浏览器中。留空则清除。</p>
    </form>
  );

  if (loading || !form || !settings || !dataSettings) {
    return (
      <div className="mx-auto max-w-5xl space-y-6 p-6">
        <div className="space-y-2">
          <h1 className="text-2xl font-semibold tracking-tight">设置</h1>
          <p className="max-w-3xl text-sm text-muted-foreground">配置模型凭证和市场数据源令牌。</p>
        </div>
        {localApiAccessSection}
        <div className="flex min-h-32 items-center justify-center rounded-lg border bg-card p-5 text-sm text-muted-foreground">
          {settingsLoadError ? (
            <div className="text-center">
              <div className="font-medium text-foreground">设置不可用</div>
              <div className="mt-1">{settingsLoadError}</div>
            </div>
          ) : (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              {"Loading..."}
            </>
          )}
        </div>
      </div>
    );
  }

  const keyStatus = settings.api_key_configured
    ? "已配置"
    : settings.api_key_required
      ? "留空则保留当前密钥"
      : selectedProvider?.auth_type === "oauth" && selectedProvider.login_command
        ? `此提供商使用OAuth。运行: ${selectedProvider.login_command}`
        : "此提供商不需要API密钥。";
  const apiKeyDisabled = !selectedProvider?.api_key_required || clearApiKey;
  const tushareStatus = dataSettings.tushare_token_configured
    ? "已配置"
    : "留空则保留当前token";

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">{"Settings"}</h1>
        <p className="max-w-3xl text-sm text-muted-foreground">{"Configure model credentials and market data source tokens for this local project."}</p>
      </div>

      {localApiAccessSection}

      <div className="space-y-2">
        <h2 className="text-lg font-semibold tracking-tight">LLM设置</h2>
        <p className="max-w-3xl text-sm text-muted-foreground">选择代理使用的模型并保存到项目本地 agent/.env 文件。</p>
      </div>

      <form onSubmit={submit} className="grid gap-6 lg:grid-cols-[minmax(0,1.4fr)_minmax(320px,0.8fr)]">
        <section className="rounded-lg border bg-card p-5 shadow-sm">
          <div className="mb-5 flex items-center gap-2">
            <Server className="h-4 w-4 text-primary" />
            <h2 className="text-base font-semibold">连接</h2>
          </div>

          <div className="grid gap-4">
            <label className="grid gap-2">
              <span className={labelClass}>{i18n.t("settings.provider")}</span>
              <select
                value={form.provider}
                onChange={(event) => onProviderChange(event.target.value)}
                className={fieldClass}
              >
                {providers.map((provider) => (
                  <option key={provider.name} value={provider.name}>{provider.label}</option>
                ))}
              </select>
              <span className={hintClass}>切换提供商会更新推荐模型和端点。</span>
            </label>

            <label className="grid gap-2">
              <span className={labelClass}>{"Model"}</span>
              <div className="flex gap-2">
                <input
                  value={form.model_name}
                  onChange={(event) => setForm({ ...form, model_name: event.target.value })}
                  className={fieldClass}
                  required
                />
                <button
                  type="button"
                  onClick={() => applyProviderDefaults()}
                  className="inline-flex shrink-0 items-center gap-2 rounded-md border px-3 py-2 text-sm text-muted-foreground transition hover:bg-muted hover:text-foreground"
                  title="使用提供商默认值"
                >
                  <RotateCcw className="h-4 w-4" />
                  <span className="hidden sm:inline">使用默认值</span>
                </button>
              </div>
              <span className={hintClass}>使用提供商要求的确切模型ID。</span>
            </label>

            <label className="grid gap-2">
              <span className={labelClass}>{i18n.t("settings.baseUrl")}</span>
              <input
                value={form.base_url}
                onChange={(event) => setForm({ ...form, base_url: event.target.value })}
                className={fieldClass}
                placeholder={selectedProvider?.default_base_url}
                disabled={selectedProvider?.auth_type === "oauth"}
              />
            </label>

            <label className="grid gap-2">
              <span className={labelClass}>
                {selectedProvider?.auth_type === "oauth" ? "OAuth" : "API key"}
              </span>
              <div className="relative">
                <KeyRound className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
                <input
                  type="password"
                  value={apiKey}
                  onChange={(event) => setApiKey(event.target.value)}
                  className={`${fieldClass} pl-9`}
                  placeholder={keyStatus}
                  autoComplete="current-password"
                  disabled={apiKeyDisabled}
                />
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className={hintClass}>{keyStatus}</span>
                {selectedProvider?.api_key_required ? (
                  <label className="flex shrink-0 items-center gap-2 text-xs text-muted-foreground">
                    <input
                      type="checkbox"
                      checked={clearApiKey}
                      onChange={(event) => {
                        setClearApiKey(event.target.checked);
                        if (event.target.checked) setApiKey("");
                      }}
                      className="h-3.5 w-3.5 accent-primary"
                    />
                    {"清除已保存的API密钥"}
                  </label>
                ) : null}
              </div>
            </label>
          </div>
        </section>

        <section className="rounded-lg border bg-card p-5 shadow-sm">
          <div className="mb-5 flex items-center gap-2">
            <SlidersHorizontal className="h-4 w-4 text-primary" />
            <h2 className="text-base font-semibold">生成参数</h2>
          </div>

          <div className="grid gap-4">
            <label className="grid gap-2">
              <span className={labelClass}>{i18n.t("settings.temperature")}</span>
              <input
                type="number"
                min={0}
                max={2}
                step={0.1}
                value={form.temperature}
                onChange={(event) => setForm({ ...form, temperature: Number(event.target.value) })}
                className={fieldClass}
              />
            </label>

            <label className="grid gap-2">
              <span className={labelClass}>{i18n.t("settings.timeoutSeconds")}</span>
              <input
                type="number"
                min={1}
                max={3600}
                step={1}
                value={form.timeout_seconds}
                onChange={(event) => setForm({ ...form, timeout_seconds: Number(event.target.value) })}
                className={fieldClass}
              />
            </label>

            <label className="grid gap-2">
              <span className={labelClass}>{"Max retries"}</span>
              <input
                type="number"
                min={0}
                max={20}
                step={1}
                value={form.max_retries}
                onChange={(event) => setForm({ ...form, max_retries: Number(event.target.value) })}
                className={fieldClass}
              />
            </label>

            <label className="grid gap-2">
              <span className={labelClass}>{i18n.t("settings.reasoningEffort")}</span>
              <select
                value={form.reasoning_effort}
                onChange={(event) => setForm({ ...form, reasoning_effort: event.target.value })}
                className={fieldClass}
              >
                <option value="">{"Off"}</option>
                <option value="low">low</option>
                <option value="medium">medium</option>
                <option value="high">high</option>
                <option value="max">max</option>
              </select>
              <span className={hintClass}>模型回答前的思考深度。越高越彻底但越慢；关闭可获得最快回复。</span>
            </label>

            <div className="rounded-md border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
              <span className="font-medium text-foreground">保存位置: </span>
              <span className="break-all font-mono">{settings.env_path}</span>
            </div>

            <button
              type="submit"
              disabled={saving}
              className="inline-flex items-center justify-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-70"
            >
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              {saving ? "保存中..." : "保存"}
            </button>
          </div>
        </section>
      </form>

      <form onSubmit={submitDataSources} className="rounded-lg border bg-card p-5 shadow-sm">
        <div className="mb-5 space-y-1">
          <div className="flex items-center gap-2">
            <Database className="h-4 w-4 text-primary" />
            <h2 className="text-base font-semibold">数据源设置</h2>
          </div>
          <p className="text-sm text-muted-foreground">配置回测和研究代理使用的市场数据凭证。</p>
        </div>

        <div className="grid gap-5 lg:grid-cols-[minmax(0,1.1fr)_minmax(280px,0.9fr)]">
          <div className="grid gap-4">
            <label className="grid gap-2">
              <span className={labelClass}>{"Tushare token"}</span>
              <div className="relative">
                <KeyRound className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
                <input
                  type="password"
                  value={tushareToken}
                  onChange={(event) => setTushareToken(event.target.value)}
                  className={`${fieldClass} pl-9`}
                  placeholder={tushareStatus}
                  autoComplete="current-password"
                  disabled={clearTushareToken}
                />
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className={hintClass}>用于A股、期货、基金和宏观数据。未设置时回退到AKShare。</span>
                <label className="flex shrink-0 items-center gap-2 text-xs text-muted-foreground">
                  <input
                    type="checkbox"
                    checked={clearTushareToken}
                    onChange={(event) => {
                      setClearTushareToken(event.target.checked);
                      if (event.target.checked) setTushareToken("");
                    }}
                    className="h-3.5 w-3.5 accent-primary"
                  />
                  {"清除已保存的Tushare token"}
                </label>
              </div>
            </label>

            <div className="rounded-md border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
              <span className="font-medium text-foreground">保存位置: </span>
              <span className="break-all font-mono">{dataSettings.env_path}</span>
            </div>

            <button
              type="submit"
              disabled={dataSaving}
              className="inline-flex items-center justify-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-70"
            >
              {dataSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              {dataSaving ? "保存中..." : "保存数据源设置"}
            </button>
          </div>

          <div className="rounded-md border bg-muted/20 p-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <span className="text-sm font-medium">{"BaoStock"}</span>
              <span className={`rounded-full px-2 py-0.5 text-xs ${dataSettings.baostock_supported ? "bg-success/10 text-success" : "bg-warning/10 text-warning"}`}>
                {dataSettings.baostock_supported ? "加载器可用" : "无项目加载器"}
              </span>
            </div>
            <div className="space-y-2 text-sm text-muted-foreground">
              <p>{dataSettings.baostock_message}</p>
              <p>
                {dataSettings.baostock_installed
                  ? "Python包已安装"
                  : "Python包未安装"}
              </p>
            </div>
          </div>
        </div>
      </form>
    </div>
  );
}
