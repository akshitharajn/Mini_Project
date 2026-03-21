import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  useEdgesState,
  useNodesState,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import RequireUser from '../components/RequireUser';
import { useUser } from '../context/UserContext';
import { useTheme } from '../context/ThemeContext';
import { getMindMap } from '../services/api';
import { BookOpen, FileQuestion, Network, RefreshCw, Route } from 'lucide-react';

const NODE_SIZES = {
  subject: { width: 220, height: 88 },
  unit: { width: 188, height: 70 },
  group: { width: 178, height: 66 },
  topic: { width: 196, height: 78 },
};

function getClusterCenters(count) {
  const columns = count > 1 ? 2 : 1;
  return Array.from({ length: count }, (_, index) => {
    const row = Math.floor(index / columns);
    const column = index % columns;
    return {
      x: column * 980,
      y: row * 860,
    };
  });
}

function getNodeStyle(node) {
  const palette = {
    subject: 'linear-gradient(135deg, color-mix(in srgb, var(--primary) 88%, white), color-mix(in srgb, var(--accent) 60%, var(--primary)))',
    unit: 'color-mix(in srgb, var(--primary) 18%, var(--surface-strong))',
    group: 'color-mix(in srgb, var(--accent) 14%, var(--surface-strong))',
    topic: 'var(--surface-strong)',
  };
  const sizes = NODE_SIZES[node.node_type] || NODE_SIZES.topic;

  return {
    width: sizes.width,
    minHeight: sizes.height,
    borderRadius: node.node_type === 'subject' ? 24 : 18,
    border: `1px solid color-mix(in srgb, ${node.color} 38%, var(--border))`,
    background: palette[node.node_type] || palette.topic,
    color: 'var(--text)',
    boxShadow: node.node_type === 'subject'
      ? '0 18px 38px color-mix(in srgb, var(--primary) 28%, transparent)'
      : '0 10px 28px rgba(17, 31, 53, 0.08)',
    padding: 14,
    fontWeight: node.node_type === 'subject' ? 700 : 600,
    fontSize: node.node_type === 'topic' ? '0.88rem' : '0.92rem',
    lineHeight: 1.25,
  };
}

function layoutGraph(graph, subjectFilter) {
  const filteredNodes = graph.nodes.filter((node) => subjectFilter === 'all' || node.subject_id === subjectFilter);
  const visibleIds = new Set(filteredNodes.map((node) => node.id));
  const filteredEdges = graph.edges.filter((edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target));
  const containsEdges = filteredEdges.filter((edge) => edge.relationship_type === 'contains');
  const childrenBySource = new Map();

  containsEdges.forEach((edge) => {
    const children = childrenBySource.get(edge.source) || [];
    children.push(edge.target);
    childrenBySource.set(edge.source, children);
  });

  const nodeById = new Map(filteredNodes.map((node) => [node.id, node]));
  const roots = filteredNodes.filter((node) => node.node_type === 'subject').sort((a, b) => a.label.localeCompare(b.label));
  const centers = getClusterCenters(roots.length || 1);
  const positions = new Map();
  const ringSpacing = 184;

  function placeChildren(parentId, center, depth, startAngle, endAngle) {
    const childIds = (childrenBySource.get(parentId) || [])
      .slice()
      .sort((left, right) => {
        const leftNode = nodeById.get(left);
        const rightNode = nodeById.get(right);
        return (leftNode?.label || '').localeCompare(rightNode?.label || '');
      });

    if (childIds.length === 0) return;

    const span = (endAngle - startAngle) / childIds.length;
    childIds.forEach((childId, index) => {
      const childStart = startAngle + span * index;
      const childEnd = childStart + span;
      const angle = (childStart + childEnd) / 2;
      positions.set(childId, {
        x: center.x + Math.cos(angle) * ringSpacing * depth,
        y: center.y + Math.sin(angle) * ringSpacing * depth,
      });
      placeChildren(childId, center, depth + 1, childStart, childEnd);
    });
  }

  roots.forEach((root, index) => {
    const center = centers[index];
    positions.set(root.id, center);
    placeChildren(root.id, center, 1, -Math.PI, Math.PI);
  });

  const nodes = filteredNodes.map((node) => ({
    id: node.id,
    type: 'default',
    data: { label: node.label, mapNode: node },
    position: positions.get(node.id) || { x: 0, y: 0 },
    draggable: true,
    className: `mind-map-node mind-map-node-${node.node_type}`,
    style: getNodeStyle(node),
  }));

  const edges = filteredEdges.map((edge) => {
    const palette = {
      contains: {
        stroke: 'color-mix(in srgb, var(--primary) 46%, var(--border))',
        strokeWidth: 2,
        strokeDasharray: '0',
      },
      prerequisite: {
        stroke: 'color-mix(in srgb, var(--accent) 82%, var(--border))',
        strokeWidth: 2,
        strokeDasharray: '7 5',
      },
      related: {
        stroke: 'color-mix(in srgb, var(--text-muted) 72%, var(--border))',
        strokeWidth: 1.5,
        strokeDasharray: '4 5',
      },
    };

    return {
      id: edge.id,
      source: edge.source,
      target: edge.target,
      type: 'smoothstep',
      animated: edge.relationship_type === 'prerequisite',
      label: edge.relationship_type === 'contains' ? '' : edge.label,
      style: palette[edge.relationship_type] || palette.related,
      labelStyle: { fill: 'var(--text-muted)', fontWeight: 600, fontSize: 11 },
      labelBgStyle: { fill: 'var(--surface-strong)', fillOpacity: 0.86 },
    };
  });

  return { nodes, edges };
}

export default function MindMap() {
  const { userId } = useUser();
  const { resolvedTheme } = useTheme();
  const navigate = useNavigate();
  const [graph, setGraph] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [selectedNode, setSelectedNode] = useState(null);
  const [subjectFilter, setSubjectFilter] = useState('all');
  const [reactFlowInstance, setReactFlowInstance] = useState(null);
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);

  useEffect(() => {
    if (!userId) return;

    let cancelled = false;

    const loadGraph = async ({ silent = false } = {}) => {
      if (!silent) setLoading(true);
      try {
        const { data } = await getMindMap(userId);
        if (cancelled) return;
        setGraph(data);
        setError('');
      } catch (loadError) {
        if (cancelled) return;
        setError(loadError.response?.data?.detail || 'Could not load the mind map.');
      } finally {
        if (!cancelled && !silent) setLoading(false);
      }
    };

    loadGraph();

    const interval = window.setInterval(() => {
      loadGraph({ silent: true });
    }, 30000);

    const handleFocus = () => loadGraph({ silent: true });
    window.addEventListener('focus', handleFocus);

    return () => {
      cancelled = true;
      window.clearInterval(interval);
      window.removeEventListener('focus', handleFocus);
    };
  }, [userId]);

  useEffect(() => {
    if (!graph) {
      setNodes([]);
      setEdges([]);
      return;
    }

    const layout = layoutGraph(graph, subjectFilter);
    setNodes(layout.nodes);
    setEdges(layout.edges);

    if (selectedNode && !layout.nodes.some((node) => node.id === selectedNode.id)) {
      setSelectedNode(null);
    }
  }, [graph, subjectFilter, selectedNode, setEdges, setNodes]);

  useEffect(() => {
    if (!reactFlowInstance || nodes.length === 0) return;
    const frame = window.requestAnimationFrame(() => {
      reactFlowInstance.fitView({ padding: 0.18, duration: 500 });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [reactFlowInstance, nodes, edges]);

  const refreshGraph = async () => {
    if (!userId) return;
    setLoading(true);
    try {
      const { data } = await getMindMap(userId);
      setGraph(data);
      setError('');
    } catch (loadError) {
      setError(loadError.response?.data?.detail || 'Could not refresh the mind map.');
    } finally {
      setLoading(false);
    }
  };

  const subjectOptions = graph?.nodes.filter((node) => node.node_type === 'subject') || [];

  return (
    <RequireUser>
      <div className="page page-wide">
        <div className="page-header-row mind-map-header-row">
          <div>
            <h1 className="page-title">Mind Map</h1>
            <p className="page-subtitle">
              Visualize learning paths, concept clusters, and prerequisite flows across every subject.
            </p>
          </div>
          <button className="btn btn-outline" type="button" onClick={refreshGraph} disabled={loading}>
            <RefreshCw size={16} className={loading ? 'spin' : ''} /> Refresh Map
          </button>
        </div>

        <div className="mind-map-stats">
          <div className="mind-map-stat">
            <span>Subjects</span>
            <strong>{graph?.subject_count || 0}</strong>
          </div>
          <div className="mind-map-stat">
            <span>Topics</span>
            <strong>{graph?.topic_count || 0}</strong>
          </div>
          <div className="mind-map-stat">
            <span>Graph Nodes</span>
            <strong>{graph?.node_count || 0}</strong>
          </div>
          <div className="mind-map-stat">
            <span>Connections</span>
            <strong>{graph?.edge_count || 0}</strong>
          </div>
        </div>

        <div className="mind-map-page">
          <section className="card mind-map-shell">
            <div className="mind-map-toolbar">
              <div className="mind-map-legend">
                <span><i className="legend-dot subject" /> Subject</span>
                <span><i className="legend-dot unit" /> Unit</span>
                <span><i className="legend-dot group" /> Parent Concept</span>
                <span><i className="legend-dot topic" /> Topic</span>
              </div>
              <label className="mind-map-filter">
                <span>Filter subject</span>
                <select value={subjectFilter} onChange={(event) => setSubjectFilter(event.target.value)}>
                  <option value="all">All subjects</option>
                  {subjectOptions.map((subject) => (
                    <option key={subject.id} value={subject.subject_id}>
                      {subject.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            {error ? (
              <div className="mind-map-empty">
                <strong>Mind map unavailable</strong>
                <p>{error}</p>
              </div>
            ) : loading ? (
              <div className="mind-map-empty">
                <strong>Building your graph…</strong>
                <p>Collecting subjects, topics, and inferred learning paths.</p>
              </div>
            ) : nodes.length === 0 ? (
              <div className="mind-map-empty">
                <strong>No topics mapped yet</strong>
                <p>Add subjects or import syllabus topics to generate the graph automatically.</p>
              </div>
            ) : (
              <div className="mind-map-canvas">
                <ReactFlow
                  nodes={nodes}
                  edges={edges}
                  onNodesChange={onNodesChange}
                  onEdgesChange={onEdgesChange}
                  onNodeClick={(_, node) => setSelectedNode(node.data.mapNode)}
                  onInit={setReactFlowInstance}
                  fitView
                  proOptions={{ hideAttribution: true }}
                  defaultEdgeOptions={{ type: 'smoothstep' }}
                  minZoom={0.2}
                  maxZoom={1.6}
                >
                  <MiniMap
                    pannable
                    zoomable
                    maskColor={resolvedTheme === 'dark' ? 'rgba(8, 16, 28, 0.65)' : 'rgba(255, 255, 255, 0.72)'}
                    nodeColor={(node) => node.data.mapNode.color}
                  />
                  <Controls />
                  <Background gap={18} size={1.2} color={resolvedTheme === 'dark' ? '#24415b' : '#bfd1e2'} />
                </ReactFlow>
              </div>
            )}
          </section>

          <aside className="card mind-map-inspector">
            {selectedNode ? (
              <>
                <div className="mind-map-inspector-top">
                  <span className={`mind-map-node-badge ${selectedNode.node_type}`}>{selectedNode.node_type}</span>
                  <h3>{selectedNode.label}</h3>
                  <p>{selectedNode.summary}</p>
                </div>

                <div className="mind-map-meta">
                  <div>
                    <span>Subject</span>
                    <strong>{selectedNode.subject_name}</strong>
                  </div>
                  <div>
                    <span>Full name</span>
                    <strong>{selectedNode.full_name || selectedNode.label}</strong>
                  </div>
                  {selectedNode.unit_name && (
                    <div>
                      <span>Unit</span>
                      <strong>{selectedNode.unit_name}</strong>
                    </div>
                  )}
                  {typeof selectedNode.estimated_hours === 'number' && (
                    <div>
                      <span>Estimated study time</span>
                      <strong>{selectedNode.estimated_hours.toFixed(1)} hrs</strong>
                    </div>
                  )}
                  {typeof selectedNode.completion_pct === 'number' && (
                    <div>
                      <span>Completion</span>
                      <strong>{Math.round(selectedNode.completion_pct)}%</strong>
                    </div>
                  )}
                </div>

                <div className="mind-map-actions">
                  <button
                    className="btn btn-primary"
                    type="button"
                    onClick={() =>
                      navigate('/subjects', {
                        state: {
                          subjectId: selectedNode.subject_id,
                          topicId: selectedNode.topic_id,
                        },
                      })
                    }
                  >
                    <BookOpen size={16} /> Open Study Material
                  </button>
                  <button
                    className="btn btn-outline"
                    type="button"
                    onClick={() =>
                      selectedNode.topic_id &&
                      navigate('/quiz', {
                        state: { topicId: selectedNode.topic_id },
                      })
                    }
                    disabled={!selectedNode.topic_id}
                  >
                    <FileQuestion size={16} /> Open Quiz
                  </button>
                </div>
              </>
            ) : (
              <div className="mind-map-empty-state">
                <Network size={28} />
                <h3>Select a node</h3>
                <p>Inspect a subject, unit, or topic to see its relationships and jump into study or quiz flows.</p>
              </div>
            )}

            <div className="mind-map-note">
              <Route size={16} />
              <span>
                The graph refreshes automatically while this page is open and whenever the window regains focus.
              </span>
            </div>
          </aside>
        </div>
      </div>
    </RequireUser>
  );
}