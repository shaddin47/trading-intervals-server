import { useEffect, useState, useCallback } from 'react'
import type { MarketGroupConfig } from '@/types'
import { fetchConfigs, patchConfig, deleteConfig, upsertConfig } from '@/utils/api'
import { useApp } from '@/hooks/useApp'

interface SaveState {
  key: string
  status: 'saving' | 'saved' | 'error'
}

export function ConfigPage() {
  const { env, patchGroupComment, patchGroupIgnored, patchGroupName } = useApp()
  const [rows, setRows]         = useState<MarketGroupConfig[]>([])
  const [loading, setLoading]   = useState(true)
  const [saveState, setSaveState] = useState<SaveState | null>(null)
  const [deferredWarning, setDeferredWarning] = useState(false)
  const [newRow, setNewRow]     = useState<Partial<MarketGroupConfig> | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    fetchConfigs(env)
      .then(setRows)
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [env])

  useEffect(() => { load() }, [load])

  async function handlePatch(
    row: MarketGroupConfig,
    field: keyof MarketGroupConfig,
    value: string | boolean,
  ) {
    const key = `${row.route_group_id}-${row.name}-${field}`
    setSaveState({ key, status: 'saving' })
    try {
      const updated = await patchConfig(env, row.route_group_id, row.name, { [field]: value })
      setRows(prev => prev.map(r =>
        r.route_group_id === row.route_group_id && r.name === row.name ? updated : r
      ))
      // Propagate changes to the Gantt groups cache immediately
      if (field === 'comment') {
        patchGroupComment(row.route_group_id, row.name, value as string | null)
      }
      if (field === 'ignore') {
        patchGroupIgnored(row.route_group_id, row.name, value as boolean)
      }
      if (field === 'name') {
        patchGroupName(row.route_group_id, row.name, value as string)
      }
      if (['task_name', 'exchange_keys_csv', 'exchange_keys_from_viable_routes'].includes(field)) {
        setDeferredWarning(true)
      }
      setSaveState({ key, status: 'saved' })
      setTimeout(() => setSaveState(null), 2000)
    } catch {
      setSaveState({ key, status: 'error' })
    }
  }

  async function handleDelete(row: MarketGroupConfig) {
    if (!confirm(`Remove override for "${row.name}"? The group will revert to its default DB name.`)) return
    try {
      await deleteConfig(env, row.route_group_id, row.name)
      setDeferredWarning(true)
      setRows(prev => prev.filter(r =>
        !(r.route_group_id === row.route_group_id && r.name === row.name)
      ))
    } catch (e) {
      alert('Delete failed: ' + String(e))
    }
  }

  async function handleAdd() {
    if (!newRow?.name || !newRow?.route_group_id) return
    const cfg: MarketGroupConfig = {
      env,
      route_group_id: Number(newRow.route_group_id),
      name: newRow.name,
      task_name: newRow.task_name ?? null,
      exchange_keys_csv: newRow.exchange_keys_csv ?? null,
      exchange_keys_from_viable_routes: newRow.exchange_keys_from_viable_routes ?? false,
      ignore: newRow.ignore ?? false,
      comment: newRow.comment ?? null,
    }
    try {
      const created = await upsertConfig(cfg)
      setDeferredWarning(true)
      setRows(prev => [...prev, created])
      setNewRow(null)
    } catch (e) {
      alert('Save failed: ' + String(e))
    }
  }

  if (loading) {
    return (
      <div className="config-page">
        <div className="state-msg"><div className="spinner" />Loading config…</div>
      </div>
    )
  }

  return (
    <div className="config-page">
      {deferredWarning && (
        <div className="deferred-warning">
          <span>⚠ Some changes (task aliases, exchange keys, added/removed rows) will take effect on the next data refresh.</span>
          <button onClick={() => setDeferredWarning(false)}>✕</button>
        </div>
      )}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>Market Group Config — {env}</h2>
        <button
          className="icon-btn"
          style={{ width: 'auto', padding: '0 10px', fontFamily: 'var(--mono)', fontSize: 10 }}
          onClick={() => setNewRow({})}
        >
          + Add row
        </button>
      </div>

      <table className="config-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>Name</th>
            <th>Task name aliases</th>
            <th>Exchange keys CSV</th>
            <th style={{ textAlign: 'center' }}>Viable routes</th>
            <th style={{ textAlign: 'center' }}>Ignore</th>
            <th>Comment (tooltip)</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {rows.map(row => {
            const baseKey = `${row.route_group_id}-${row.name}`
            return (
              <tr key={baseKey}>
                <td className="mono">{row.route_group_id}</td>
                <td>
                  <EditableCell
                    value={row.name}
                    onCommit={v => handlePatch(row, 'name', v)}
                    saveKey={`${baseKey}-name`}
                    saveState={saveState}
                  />
                </td>
                <td>
                  <EditableCell
                    value={row.task_name ?? ''}
                    placeholder="e.g. ICE;iceuk"
                    onCommit={v => handlePatch(row, 'task_name', v || null as any)}
                    saveKey={`${baseKey}-task_name`}
                    saveState={saveState}
                  />
                </td>
                <td>
                  <EditableCell
                    value={row.exchange_keys_csv ?? ''}
                    placeholder="e.g. 27,509"
                    onCommit={v => handlePatch(row, 'exchange_keys_csv', v || null as any)}
                    saveKey={`${baseKey}-exchange_keys_csv`}
                    saveState={saveState}
                  />
                </td>
                <td style={{ textAlign: 'center' }}>
                  <label className="toggle">
                    <input
                      type="checkbox"
                      checked={row.exchange_keys_from_viable_routes}
                      onChange={e => handlePatch(row, 'exchange_keys_from_viable_routes', e.target.checked)}
                    />
                    <span className="toggle-slider" />
                  </label>
                </td>
                <td style={{ textAlign: 'center' }}>
                  <label className="toggle">
                    <input
                      type="checkbox"
                      checked={row.ignore}
                      onChange={e => handlePatch(row, 'ignore', e.target.checked)}
                    />
                    <span className="toggle-slider" />
                  </label>
                </td>
                <td>
                  <EditableCell
                    value={row.comment ?? ''}
                    placeholder="Tooltip comment…"
                    onCommit={v => handlePatch(row, 'comment', v || null as any)}
                    saveKey={`${baseKey}-comment`}
                    saveState={saveState}
                  />
                </td>
                <td>
                  <button
                    className="icon-btn"
                    style={{ border: 'none', background: 'none', color: 'var(--conflict-hi)', fontSize: 14 }}
                    title="Remove override"
                    onClick={() => handleDelete(row)}
                  >×</button>
                </td>
              </tr>
            )
          })}

          {/* New row form */}
          {newRow !== null && (
            <tr style={{ background: 'var(--bg-3)' }}>
              <td>
                <input
                  className="editable-cell"
                  placeholder="Route group ID"
                  type="number"
                  value={newRow.route_group_id ?? ''}
                  onChange={e => setNewRow(r => ({ ...r, route_group_id: Number(e.target.value) }))}
                />
              </td>
              <td>
                <input
                  className="editable-cell"
                  placeholder="Display name"
                  value={newRow.name ?? ''}
                  onChange={e => setNewRow(r => ({ ...r, name: e.target.value }))}
                />
              </td>
              <td>
                <input
                  className="editable-cell"
                  placeholder="task;alias"
                  value={newRow.task_name ?? ''}
                  onChange={e => setNewRow(r => ({ ...r, task_name: e.target.value }))}
                />
              </td>
              <td>
                <input
                  className="editable-cell"
                  placeholder="27,509"
                  value={newRow.exchange_keys_csv ?? ''}
                  onChange={e => setNewRow(r => ({ ...r, exchange_keys_csv: e.target.value }))}
                />
              </td>
              <td style={{ textAlign: 'center' }}>
                <label className="toggle">
                  <input
                    type="checkbox"
                    checked={newRow.exchange_keys_from_viable_routes ?? false}
                    onChange={e => setNewRow(r => ({ ...r, exchange_keys_from_viable_routes: e.target.checked }))}
                  />
                  <span className="toggle-slider" />
                </label>
              </td>
              <td style={{ textAlign: 'center' }}>
                <label className="toggle">
                  <input
                    type="checkbox"
                    checked={newRow.ignore ?? false}
                    onChange={e => setNewRow(r => ({ ...r, ignore: e.target.checked }))}
                  />
                  <span className="toggle-slider" />
                </label>
              </td>
              <td>
                <input
                  className="editable-cell"
                  placeholder="Comment…"
                  value={newRow.comment ?? ''}
                  onChange={e => setNewRow(r => ({ ...r, comment: e.target.value }))}
                />
              </td>
              <td style={{ display: 'flex', gap: 4, padding: '5px 6px' }}>
                <button
                  className="icon-btn"
                  style={{ width: 'auto', padding: '0 8px', fontFamily: 'var(--mono)', fontSize: 10, color: 'var(--ok-hi)' }}
                  onClick={handleAdd}
                >✓</button>
                <button
                  className="icon-btn"
                  style={{ border: 'none', color: 'var(--text-dim)' }}
                  onClick={() => setNewRow(null)}
                >×</button>
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

interface EditableCellProps {
  value: string
  placeholder?: string
  onCommit: (v: string) => void
  saveKey: string
  saveState: SaveState | null
}

function EditableCell({ value, placeholder, onCommit, saveKey, saveState }: EditableCellProps) {
  const [local, setLocal] = useState(value)

  useEffect(() => setLocal(value), [value])

  const isSaving = saveState?.key === saveKey && saveState.status === 'saving'
  const isSaved  = saveState?.key === saveKey && saveState.status === 'saved'

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
      <input
        className="editable-cell"
        value={local}
        placeholder={placeholder}
        onChange={e => setLocal(e.target.value)}
        onBlur={() => { if (local !== value) onCommit(local) }}
        onKeyDown={e => { if (e.key === 'Enter') onCommit(local) }}
        disabled={isSaving}
      />
      {isSaving && <span style={{ color: 'var(--text-xdim)', fontFamily: 'var(--mono)', fontSize: 10 }}>…</span>}
      {isSaved  && <span className="save-indicator">✓</span>}
    </div>
  )
}
