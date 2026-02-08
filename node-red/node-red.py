"""
Node-RED Plugin for InkyPi
This plugin fetches JSON data from a Node-RED HTTP endpoint and displays it on the e-ink display.
"""

from plugins.base_plugin.base_plugin import BasePlugin
from PIL import Image
import logging
import requests
import json
import os
from utils.image_utils import take_screenshot_html

logger = logging.getLogger(__name__)


class NodeRed(BasePlugin):
    """Plugin for displaying Node-RED data on InkyPi."""
    
    def generate_image(self, settings, device_config):
        """
        Generate an image from Node-RED data.
        
        Args:
            settings: A dictionary of plugin configuration values
            device_config: An instance of the Config class
            
        Returns:
            PIL.Image: The generated image
        """
        # Get settings with defaults
        node_red_url = settings.get('nodeRedUrl', 'http://localhost:1880').strip().rstrip('/')
        endpoint_path = settings.get('endpointPath', '/inkypi/data').strip()
        timeout = int(settings.get('timeout', 10))
        
        # Validate settings
        if not node_red_url:
            logger.error("Node-RED URL is required")
            raise RuntimeError("Node-RED URL is required.")
        
        if not endpoint_path:
            logger.error("Endpoint path is required")
            raise RuntimeError("Endpoint path is required.")
        
        # Construct full URL
        full_url = f"{node_red_url}{endpoint_path}"
        logger.info(f"Fetching data from Node-RED: {full_url}")
        
        try:
            # Make HTTP GET request
            logger.debug(f"Making HTTP GET request to {full_url} with timeout {timeout}s")
            response = requests.get(full_url, timeout=timeout)
            
            # Log response details
            logger.info(f"HTTP Status Code: {response.status_code}")
            logger.debug(f"Response Headers: {dict(response.headers)}")
            
            # Check for HTTP errors
            response.raise_for_status()
            
            # Get display dimensions
            dimensions = device_config.get_resolution()
            if device_config.get_config("orientation") == "vertical":
                dimensions = dimensions[::-1]
            
            # Check if HTML mode is enabled
            html_mode = settings.get('htmlMode', 'false') == 'true'
            
            if html_mode:
                # HTML Mode: Node-RED sends complete HTML, render it directly
                logger.info("HTML Mode enabled - rendering HTML directly from Node-RED")
                html_content = response.text
                logger.debug(f"HTML Content length: {len(html_content)} characters")
                logger.debug(f"HTML Content preview: {html_content[:500]}")
                
                # Write HTML to preview file for debugging
                preview_path = os.path.join(self.get_plugin_dir(), "preview.html")
                try:
                    with open(preview_path, 'w', encoding='utf-8') as f:
                        f.write(html_content)
                    logger.info(f"HTML written to preview file: {preview_path}")
                except Exception as e:
                    logger.warning(f"Failed to write preview.html: {e}")
                
                # Render HTML directly using take_screenshot_html
                image = take_screenshot_html(html_content, dimensions)
                logger.info("Successfully rendered HTML from Node-RED")
                return image
            else:
                # JSON Mode: Parse JSON and use layout configuration
                logger.info("JSON Mode enabled - parsing JSON and using layout configuration")
                
                # Parse JSON response
                try:
                    data = response.json()
                    logger.info(f"Successfully fetched JSON data from Node-RED")
                    logger.debug(f"JSON Data: {json.dumps(data, indent=2)}")
                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON response: {e}")
                    logger.debug(f"Response content: {response.text[:500]}")
                    raise RuntimeError("Node-RED returned invalid JSON data.")
                
                # Process layout configuration
                page_title = settings.get('pageTitle', '').strip()
                divisions = self._parse_divisions(settings)
                
                # If no divisions configured, show raw JSON as fallback
                if not divisions:
                    logger.warning("No divisions configured, displaying raw JSON")
                    json_string = json.dumps(data, indent=2, ensure_ascii=False)
                    template_params = {
                        "page_title": page_title,
                        "divisions": [],
                        "json_fallback": json_string,
                        "endpoint_url": full_url,
                        "plugin_settings": settings
                    }
                else:
                    # Process each division and extract data
                    processed_divisions = []
                    for division in divisions:
                        processed_lines = []
                        for line in division.get('outputLines', []):
                            processed_line = self._process_output_line(line, data)
                            processed_lines.append(processed_line)
                        processed_divisions.append({'outputLines': processed_lines})
                    
                    template_params = {
                        "page_title": page_title,
                        "divisions": processed_divisions,
                        "endpoint_url": full_url,
                        "plugin_settings": settings
                    }
                
                # Render the data using template
                image = self.render_image(
                    dimensions,
                    "node_red.html",
                    "node_red.css",
                    template_params
                )
            
            logger.info("Successfully generated image from Node-RED data")
            return image
            
        except requests.exceptions.Timeout:
            logger.error(f"Request to {full_url} timed out after {timeout}s")
            raise RuntimeError(f"Request to Node-RED timed out after {timeout} seconds.")
        
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Failed to connect to Node-RED at {full_url}: {e}")
            raise RuntimeError(f"Failed to connect to Node-RED. Check the URL and ensure Node-RED is running.")
        
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error from Node-RED: {e}")
            status_code = response.status_code if 'response' in locals() else 'unknown'
            raise RuntimeError(f"Node-RED returned HTTP error {status_code}.")
        
        except RuntimeError:
            # Re-raise RuntimeErrors as-is (they already have user-friendly messages)
            raise
        
        except Exception as e:
            logger.error(f"Unexpected error fetching Node-RED data: {e}", exc_info=True)
            raise RuntimeError(f"Failed to fetch data from Node-RED: {str(e)}")
    
    def render_image(self, dimensions, html_file, css_file=None, template_params={}):
        """
        Override render_image to log the rendered HTML for debugging.
        """
        import os
        from utils.app_utils import resolve_path, get_fonts
        from utils.image_utils import take_screenshot_html
        
        # Get paths (same as base class)
        BASE_PLUGIN_DIR = os.path.join(resolve_path("plugins"), "base_plugin")
        BASE_PLUGIN_RENDER_DIR = os.path.join(BASE_PLUGIN_DIR, "render")
        STATIC_DIR = resolve_path("static")
        
        # Load CSS files
        css_files = [os.path.join(BASE_PLUGIN_RENDER_DIR, "plugin.css")]
        if css_file:
            plugin_css = os.path.join(self.render_dir, css_file)
            css_files.append(plugin_css)
        
        # Prepare template parameters
        template_params["style_sheets"] = css_files
        template_params["width"] = dimensions[0]
        template_params["height"] = dimensions[1]
        template_params["font_faces"] = get_fonts()
        template_params["static_dir"] = STATIC_DIR
        
        # Use the parent's env if available, otherwise create one
        if hasattr(self, 'env') and self.env:
            template = self.env.get_template(html_file)
        else:
            from jinja2 import Environment, FileSystemLoader, select_autoescape
            loader = FileSystemLoader([self.render_dir, BASE_PLUGIN_RENDER_DIR])
            env = Environment(
                loader=loader,
                autoescape=select_autoescape(['html', 'xml'])
            )
            template = env.get_template(html_file)
        
        rendered_html = template.render(template_params)
        
        # Write the rendered HTML to preview.html in plugin directory for inspection
        preview_path = os.path.join(self.get_plugin_dir(), "preview.html")
        try:
            with open(preview_path, 'w', encoding='utf-8') as f:
                f.write(rendered_html)
            logger.info(f"Rendered HTML written to: {preview_path}")
        except Exception as e:
            logger.warning(f"Failed to write preview.html: {e}")
        
        
        # Convert to image
        return take_screenshot_html(rendered_html, dimensions)
    
    def _parse_divisions(self, settings):
        """Parse divisions from settings form data."""
        divisions = []
        
        # Find all division indices
        division_indices = set()
        for key in settings.keys():
            if key.startswith('division_') and '_type[]' in key:
                # Extract division index from key like "division_0_type[]"
                parts = key.split('_')
                if len(parts) >= 2:
                    try:
                        division_indices.add(int(parts[1]))
                    except ValueError:
                        continue
        
        # Sort to maintain order
        division_indices = sorted(division_indices)
        
        # Build divisions structure
        for div_idx in division_indices:
            # Get all output lines for this division
            type_keys = [k for k in settings.keys() if k == f'division_{div_idx}_type[]' or k.startswith(f'division_{div_idx}_type[')]
            value_keys = [k for k in settings.keys() if k == f'division_{div_idx}_value[]' or k.startswith(f'division_{div_idx}_value[')]
            format_keys = [k for k in settings.keys() if k == f'division_{div_idx}_format[]' or k.startswith(f'division_{div_idx}_format[')]
            font_keys = [k for k in settings.keys() if k == f'division_{div_idx}_font[]' or k.startswith(f'division_{div_idx}_font[')]
            size_keys = [k for k in settings.keys() if k == f'division_{div_idx}_size[]' or k.startswith(f'division_{div_idx}_size[')]
            color_keys = [k for k in settings.keys() if k == f'division_{div_idx}_color[]' or k.startswith(f'division_{div_idx}_color[')]
            alignment_keys = [k for k in settings.keys() if k == f'division_{div_idx}_alignment[]' or k.startswith(f'division_{div_idx}_alignment[')]
            
            # Handle array format (settings may come as arrays or single values)
            def get_array_value(keys):
                if not keys:
                    return []
                values = []
                for key in sorted(keys):
                    val = settings.get(key)
                    if isinstance(val, list):
                        values.extend(val)
                    elif val is not None:
                        values.append(val)
                return values
            
            types = get_array_value(type_keys)
            values = get_array_value(value_keys)
            formats = get_array_value(format_keys)
            fonts = get_array_value(font_keys)
            sizes = get_array_value(size_keys)
            colors = get_array_value(color_keys)
            alignments = get_array_value(alignment_keys)
            
            # Build output lines
            output_lines = []
            max_lines = max(len(types), len(values), len(formats), len(fonts), len(sizes), len(colors), len(alignments))
            
            for i in range(max_lines):
                output_line = {
                    'type': types[i] if i < len(types) else 'dataoutput',
                    'value': values[i] if i < len(values) else '',
                    'format': formats[i] if i < len(formats) else '{value}',
                    'font': fonts[i] if i < len(fonts) else 'Jost',
                    'size': sizes[i] if i < len(sizes) else 'normal',
                    'color': colors[i] if i < len(colors) else '#000000',
                    'alignment': alignments[i] if i < len(alignments) else 'left'
                }
                output_lines.append(output_line)
            
            if output_lines:
                divisions.append({'outputLines': output_lines})
        
        return divisions
    
    def _process_output_line(self, line, json_data):
        """Process a single output line and extract data from JSON."""
        line_type = line.get('type', 'dataoutput')
        value = line.get('value', '').strip()
        format_str = line.get('format', '{value}').strip()
        
        processed_line = {
            'type': line_type,
            'font': line.get('font', 'Jost'),
            'size': line.get('size', 'normal'),
            'color': line.get('color', '#000000'),
            'alignment': line.get('alignment', 'left'),
            'display_text': ''
        }
        
        if line_type == 'title':
            processed_line['display_text'] = value
        elif line_type == 'divider':
            # Divider is just a visual separator, no text needed
            processed_line['display_text'] = ''
        elif line_type == 'dataoutput':
            # Extract data from JSON using key path (supports nested keys like "sensor.temperature")
            data_value = self._extract_json_value(json_data, value)
            
            # Replace placeholder in format string (use '??' if data not found)
            try:
                if data_value is None:
                    logger.warning(f"JSON key '{value}' not found in response")
                    processed_line['display_text'] = format_str.replace('{value}', '??')
                else:
                    processed_line['display_text'] = format_str.replace('{value}', str(data_value))
            except Exception as e:
                logger.error(f"Error formatting output: {e}")
                processed_line['display_text'] = str(data_value) if data_value is not None else '??'
        
        return processed_line
    
    def _extract_json_value(self, data, key_path):
        """Extract value from JSON data using dot-notation key path."""
        if not key_path:
            return None
        
        try:
            keys = key_path.split('.')
            value = data
            
            for key in keys:
                if isinstance(value, dict):
                    value = value.get(key)
                elif isinstance(value, list):
                    try:
                        idx = int(key)
                        if 0 <= idx < len(value):
                            value = value[idx]
                        else:
                            return None
                    except (ValueError, IndexError):
                        return None
                else:
                    return None
                
                if value is None:
                    return None
            
            return value
        except Exception as e:
            logger.error(f"Error extracting JSON value for key '{key_path}': {e}")
            return None
