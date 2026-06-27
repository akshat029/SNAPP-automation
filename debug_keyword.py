"""Dump the keyword dropdown item HTML structure."""
import asyncio
from dotenv import load_dotenv
load_dotenv()
from snapp_agent import SnappAgent

async def main():
    req = {
        "journal_name": "SN Comprehensive Clinical Medicine",
        "journal_id": "42399",
        "editor_name": "Michelangelo Luciani",
        "action": "update", "sections": "", "keywords": "Cardiology",
        "first_name": "Michelangelo", "last_name": "Luciani",
        "email": "", "affiliation": "", "role": "",
        "collection_name": "", "collection_id": "", "status": "",
        "unavailable_from": "", "unavailable_to": "",
    }
    agent = SnappAgent(req, no_save=True)
    await agent._launch_browser()
    await agent.login()
    await agent.page.goto("https://usermanager.nature.com/editors/42399",
                          wait_until="domcontentloaded", timeout=30000)
    await agent._wait_for_journal_page_load()
    await agent.search_editor("Michelangelo Luciani")
    await agent.click_edit_profile()
    await agent._click_next()

    # Find the keyword input area
    tag_input_info = await agent.page.evaluate("""() => {
        // Find the Tags/Keywords section
        const result = {};
        
        // Find the input by looking near "Tags" label
        const labels = document.querySelectorAll('label, h3, h4, .form-label, strong');
        for (const lbl of labels) {
            if (lbl.textContent.trim().toLowerCase().includes('tag')) {
                result.tag_label = lbl.outerHTML.substring(0, 200);
                // Get the parent form group
                let parent = lbl.parentElement;
                for (let i = 0; i < 5; i++) {
                    if (parent) {
                        const inputs = parent.querySelectorAll('input, [contenteditable]');
                        if (inputs.length > 0) {
                            result.tag_section_html = parent.innerHTML.substring(0, 2000);
                            result.input_count = inputs.length;
                            result.input_details = Array.from(inputs).map(inp => ({
                                tag: inp.tagName,
                                type: inp.type || '',
                                id: inp.id || '',
                                class: inp.className?.toString()?.substring(0, 200) || '',
                                name: inp.name || '',
                                placeholder: inp.placeholder || ''
                            }));
                            break;
                        }
                        parent = parent.parentElement;
                    }
                }
                break;
            }
        }
        
        // Also find form-control elements near keywords
        const formControls = document.querySelectorAll('.form-control');
        result.form_controls = Array.from(formControls).map(fc => ({
            class: fc.className,
            childTags: Array.from(fc.children).map(c => `${c.tagName}.${c.className?.toString()?.substring(0,50)}`).join(', '),
            hasInput: fc.querySelector('input') !== null,
            text: fc.textContent.substring(0, 100)
        }));

        return result;
    }""")
    
    print("=== TAG LABEL ===")
    print(tag_input_info.get('tag_label', 'NOT FOUND'))
    print("\n=== TAG SECTION HTML ===")
    print(tag_input_info.get('tag_section_html', 'NOT FOUND')[:1500])
    print("\n=== INPUT DETAILS ===")
    for inp in tag_input_info.get('input_details', []):
        print(f"  <{inp['tag']} type='{inp['type']}' id='{inp['id']}' class='{inp['class']}' name='{inp['name']}' placeholder='{inp['placeholder']}'>")
    print("\n=== FORM CONTROLS ===")
    for fc in tag_input_info.get('form_controls', []):
        print(f"  class='{fc['class']}' hasInput={fc['hasInput']}")
        print(f"    children: {fc['childTags']}")

    # Now type in the keyword input and dump dropdown
    # Find the actual input
    kw_input = agent.page.locator("input#editEditorKeywords, input#addEditorKeywords")
    cnt = await kw_input.count()
    print(f"\n=== KEYWORD INPUT FOUND: {cnt} ===")
    
    if cnt == 0:
        # Try broader search
        kw_input = agent.page.locator(".form-control input")
        cnt = await kw_input.count()
        print(f"Broader search found: {cnt}")
    
    if cnt > 0:
        await kw_input.first.click()
        await kw_input.first.fill("")
        for ch in "Cardio":
            await agent.page.keyboard.type(ch, delay=50)
        await asyncio.sleep(2)

        # Now dump EVERYTHING that appeared
        dropdown_html = await agent.page.evaluate("""() => {
            const result = {};
            // Find any NEW visible elements that might be dropdown items
            // Check for lists, divs with items, etc.
            const allVisible = [];
            const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
            while (walker.nextNode()) {
                const el = walker.currentNode;
                const text = (el.textContent || '').trim().toLowerCase();
                if (text.startsWith('cardio') && el.children.length === 0 && el.offsetParent !== null) {
                    allVisible.push({
                        tag: el.tagName,
                        class: el.className?.toString() || '',
                        id: el.id || '',
                        text: el.textContent.trim().substring(0, 80),
                        parent_tag: el.parentElement?.tagName || '',
                        parent_class: el.parentElement?.className?.toString()?.substring(0, 100) || '',
                        parent_id: el.parentElement?.id || '',
                        gp_tag: el.parentElement?.parentElement?.tagName || '',
                        gp_class: el.parentElement?.parentElement?.className?.toString()?.substring(0, 100) || '',
                    });
                }
            }
            result.visible_cardio_elements = allVisible;
            
            // Also dump the keyword form-control area
            const fc = document.querySelector('.form-control.focused');
            if (fc) {
                result.focused_form_control = fc.outerHTML.substring(0, 3000);
            }
            
            // Check for any datalist
            const datalists = document.querySelectorAll('datalist');
            result.datalist_count = datalists.length;
            if (datalists.length > 0) {
                result.datalist_html = datalists[0].outerHTML.substring(0, 1000);
            }
            
            // Check for any ul/ol that appeared
            const lists = document.querySelectorAll('ul, ol');
            result.visible_lists = Array.from(lists).filter(l => l.offsetParent !== null && l.children.length > 0).map(l => ({
                tag: l.tagName,
                class: l.className?.toString() || '',
                id: l.id || '',
                childCount: l.children.length,
                firstChildHTML: l.children[0]?.outerHTML?.substring(0, 200) || ''
            }));
            
            return result;
        }""")
        
        print("\n=== VISIBLE 'cardio' ELEMENTS ===")
        for el in dropdown_html.get('visible_cardio_elements', []):
            print(f"  <{el['tag']} class='{el['class']}' id='{el['id']}'> {el['text']}")
            print(f"    parent: <{el['parent_tag']} class='{el['parent_class']}' id='{el['parent_id']}'>")
            print(f"    grandparent: <{el['gp_tag']} class='{el['gp_class']}'>")
        
        print("\n=== FOCUSED FORM CONTROL ===")
        print(dropdown_html.get('focused_form_control', 'NOT FOUND')[:1000])
        
        print(f"\n=== DATALISTS: {dropdown_html.get('datalist_count', 0)} ===")
        print(dropdown_html.get('datalist_html', 'none')[:500])
        
        print("\n=== VISIBLE LISTS ===")
        for l in dropdown_html.get('visible_lists', []):
            print(f"  <{l['tag']} class='{l['class']}' id='{l['id']}'> children={l['childCount']}")
            print(f"    first child: {l['firstChildHTML']}")

    await agent._close_browser()

asyncio.run(main())
